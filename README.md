
# Poids:

Raspberry: 46g
5g      : 304g
cam     : 5g~~
RC      : 931g


# Voiture

https://hobbykoo.com/produit/wltoys-144001-buggy-4wd-1-14-lipo-2s-rtr/

80~

# Controlleur

Raspberry Pi5 
https://fr.aliexpress.com/item/1005007022197865.html

70~

# Camera

https://www.youtube.com/watch?v=aNpZXT2Ua2E
SONY-Webcam IMX327
https://fr.aliexpress.com/item/1005006233100141.html

40 ~

# 4G / 5G

https://fr.aliexpress.com/item/1005007939334352.html
E3372h

30 ~

5g:
https://openelab.io/fr/products/rm500u-cnvraspberrypi5g4g3ghat?variant=44947385712838
RM500U-CNV
raspberry pi 4b
puce pa cher

ORANGE >> COUVERTURE ET LATENCE
Série Spéciale 20Go
17,99 € par mois , Sans engagement
17,99 € /mois
Sans engagement

# CONSO

BATTERIE: 15 ~

Donc en additionnant réaliste :

Bas/moyen : 8 W (Pi) + 1 W (cam) + 2 W (4G) ≈ 11 W

Chargé / signal 4G pas top : 12 W + 1 W + 3–4 W ≈ 16–17 W

Très pessimiste (pics) : ≈ 18–20 W

👉 On peut dire que ta conso moyenne tournera entre 12 et 17 W.

3. Converti en courant

À 5 V (côté Pi) :

12 W → 12 ÷ 5 = 2,4 A

17 W → 17 ÷ 5 = 3,4 A
Donc prévois une alim 5 V / 4 A pour être tranquille.

Si tu alimentes depuis une LiPo 3S (11,1 V) avec un buck

15 W / 11,1 V ≈ 1,35 A (ajoute 10% pour le rendement → ~1,5 A)

Si tu es en LiPo 2S (7,4 V) :

15 W / 7,4 V ≈ 2,0 A (≈ 2,2 A avec pertes)

4. Ce que ça veut dire pour l’autonomie

Exemple : LiPo 3S 2200 mAh (2,2 Ah) → 11,1 V

Puissance ≈ 15 W

Énergie batterie ≈ 11,1 × 2,2 = 24,4 Wh

Autonomie pour l’électronique seule : 24,4 ÷ 15 ≈ 1,6 h
(en vrai un peu moins à cause du buck)

Mais comme la voiture a aussi le moteur, c’est bien de séparer l’alim logicielle (Pi + 4G) du reste ou d’avoir un bon BEC/buck.



# prix moyen:

80 + 70 + 40 + 30 + 15 = 235 ~ -> 250+-
