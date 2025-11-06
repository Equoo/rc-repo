use anyhow::Result;
use bytes::Bytes;
use std::io::{self, Write};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::time::sleep;
use webrtc::api::media_engine::MediaEngine;
use webrtc::api::APIBuilder;
use webrtc::data_channel::data_channel_message::DataChannelMessage;
use webrtc::data_channel::RTCDataChannel;
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

    // When remote creates a DataChannel
    pc.on_data_channel(Box::new(move |dc: Arc<RTCDataChannel>| {
        Box::pin(async move {
            println!("DataChannel received: {}", dc.label());

            // Send periodic messages to test latency other way
            let dc_sender = Arc::clone(&dc);
            tokio::spawn(async move {
                loop {
                    let msg = format!("Hello at {:?}", Instant::now());
                    if let Err(e) = dc_sender.send(&Bytes::from(msg.clone())).await {
                        eprintln!("send error: {:?}", e);
                        break;
                    }
                    sleep(Duration::from_secs(2)).await;
                }
            });

            // Measure RTT when receiving timestamps
            let dc_reply = Arc::clone(&dc);
            dc.on_message(Box::new(move |msg: DataChannelMessage| {
                let val = dc_reply.clone();
                Box::pin(async move {
                    if msg.data.len() == 16 {
                        // Echo back to compute RTT on offer side
                        if let Err(e) = val.send(&Bytes::from(msg.data.clone())).await {
                            eprintln!("reply send error: {:?}", e);
                        }
                    } else {
                        println!("Received: {}", String::from_utf8_lossy(&msg.data));
                    }
                })
            }));
        })
    }));

    // === Read offer SDP from stdin ===
    println!("\n=== Paste OFFER from other peer and press Enter ===");
    let mut line = String::new();
    io::stdin().read_line(&mut line)?;
    let offer_json = String::from_utf8(base64::decode(line.trim())?)?;
    let offer = serde_json::from_str(&offer_json)?;
    pc.set_remote_description(offer).await?;

    // === Create and show answer SDP ===
    let answer = pc.create_answer(None).await?;
    pc.set_local_description(answer.clone()).await?;
    let sdp = serde_json::to_string(&answer)?;
    println!("\n=== Copy this ANSWER and send to the offer peer ===\n");
    println!("{}", base64::encode(sdp));

    // Keep alive
    tokio::signal::ctrl_c().await?;
    Ok(())
}

