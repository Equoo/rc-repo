use anyhow::Result;
use bytes::Bytes;
use std::io::{self, Write};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::time::sleep;
use webrtc::api::media_engine::MediaEngine;
use webrtc::api::APIBuilder;
use webrtc::data_channel::data_channel_message::DataChannelMessage;
use webrtc::ice_transport::ice_server::RTCIceServer;
use webrtc::peer_connection::configuration::RTCConfiguration;

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();

    // Build WebRTC API
    let mut m = MediaEngine::default();
    let api = APIBuilder::new().with_media_engine(m).build();

    let config = RTCConfiguration {
        ice_servers: vec![RTCIceServer {
            urls: vec!["stun:stun.l.google.com:19302".to_string()],
            ..Default::default()
        }],
        ..Default::default()
    };

    let pc = Arc::new(api.new_peer_connection(config).await?);
    let dc = pc.create_data_channel("latency", None).await?;
    let dc2 = Arc::clone(&dc);

    // When DataChannel opens: start sending pings
    dc.on_open(Box::new(move || {
        let dc3 = Arc::clone(&dc2);
        Box::pin(async move {
            println!("DataChannel open, sending pings...");
            loop {
                let now = Instant::now().elapsed().as_nanos().to_le_bytes();
                if let Err(e) = dc3.send(&Bytes::from(now.to_vec())).await {
                    eprintln!("send error: {:?}", e);
                    break;
                }
                sleep(Duration::from_secs(1)).await;
            }
        })
    }));

    // On message: measure latency
    dc.on_message(Box::new(move |msg: DataChannelMessage| {
        Box::pin(async move {
            if msg.data.len() == 16 {
                let sent_ns = u128::from_le_bytes(msg.data[..16].try_into().unwrap());
                let now = Instant::now().elapsed().as_nanos();
                let rtt = now.saturating_sub(sent_ns);
                println!("RTT: {:.2} ms", rtt as f64 / 1_000_000.0);
            } else {
                println!("Received: {}", String::from_utf8_lossy(&msg.data));
            }
        })
    }));

    // === Create and show offer SDP ===
    let offer = pc.create_offer(None).await?;
    pc.set_local_description(offer.clone()).await?;

    let sdp = serde_json::to_string(&offer)?;
    println!("\n=== Copy this OFFER and send to the other peer ===\n");
    println!("{}", base64::encode(sdp));

    // === Read answer SDP from stdin ===
    println!("\n=== Paste the ANSWER from the other peer and press Enter ===");
    let mut line = String::new();
    io::stdin().read_line(&mut line)?;
    let answer_json = String::from_utf8(base64::decode(line.trim())?)?;
    let answer = serde_json::from_str(&answer_json)?;
    pc.set_remote_description(answer).await?;

    // Wait forever
    tokio::signal::ctrl_c().await?;
    Ok(())
}

