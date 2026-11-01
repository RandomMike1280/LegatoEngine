# Piano covers to convert

185 songs, each with one solo-piano video on YouTube: well-known hits (1–65), then internet favourites
(66–185): edit songs, TikTok sounds, memes, anime, Vocaloid and game music. These are copyrighted
recordings, so they aren't downloaded for you: convert the ones you want yourself, for your own use.
Every link was checked on 25 or 26 October 2026 (the video was public then).

**In the app:** in the Convert tab, set **Type** to **Piano (or one instrument)** (faster and cleaner than
Auto for a solo piano video). Then copy the rows you want, a whole section, or this whole file, and paste them into the link
field: every link goes to the queue, which converts them one after another and saves each one. Under
**Save into**, pick or make a folder such as Covers; songs still converting or waiting are saved there. Each
song takes a few minutes.

**Or from Terminal** (run inside the AutoPiano folder; everything goes into a Covers folder):

```bash
grep -oE 'https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}' "Piano covers to convert.md" | while read -r url; do uv run autopiano-cli convert "$url" --type piano -o ~/Music/AutoPiano/Covers/ < /dev/null; done
```

Pieces marked *hard* are dense arrangements: if one sounds cluttered in Roblox, convert it again with the
Simplified style, or lower **At most**.

## Piano pieces, film and games

| # | Song | Artist | Piano version | Length | Link |
|---|---|---|---|---|---|
| 1 | River Flows in You | Yiruma | YirumaVEVO (official) | 3:30 | https://www.youtube.com/watch?v=7maJOI3QMu0 |
| 2 | Kiss the Rain | Yiruma | YirumaVEVO (official) | 3:53 | https://www.youtube.com/watch?v=imGaOIm5HOk |
| 3 | Nuvole Bianche | Ludovico Einaudi | Rousseau | 6:41 | https://www.youtube.com/watch?v=4VR-6AS0-l4 |
| 4 | Experience *(official solo piano)* | Ludovico Einaudi | Ludovico Einaudi | 5:24 | https://www.youtube.com/watch?v=O9wjmEhMKFw |
| 5 | Comptine d'un autre été (Amélie) | Yann Tiersen | Rousseau | 3:10 | https://www.youtube.com/watch?v=PaXKf0JEzEA |
| 6 | Pieces (Solo Piano) | Danilo Stankovic | Danilo Stankovic - Composer (official) | 1:27 | https://www.youtube.com/watch?v=vi84zA6iC7w |
| 7 | Je te laisserai des mots | Patrick Watson | Piano Time | 2:50 | https://www.youtube.com/watch?v=mrttX8LzYYo |
| 8 | Avril 14th | Aphex Twin | Aphex Twin (official) | 2:06 | https://www.youtube.com/watch?v=uxTdTaNIUxo |
| 9 | Mariage d'Amour | Paul de Senneville | Jacob's Piano | 4:31 | https://www.youtube.com/watch?v=FoCG-WNsZio |
| 10 | Merry-Go-Round of Life (Howl's Moving Castle) *(hard)* | Joe Hisaishi | Animenz Piano Sheets | 5:28 | https://www.youtube.com/watch?v=lB4PRX737-0 |
| 11 | One Summer's Day (Spirited Away) | Joe Hisaishi | Reynah | 5:06 | https://www.youtube.com/watch?v=8AKxbpR_cdo |
| 12 | Interstellar – Main Theme | Hans Zimmer | Patrik Pietschmann | 4:47 | https://www.youtube.com/watch?v=4y33h81phKU |
| 13 | Cornfield Chase (Interstellar) | Hans Zimmer | Kurate Music | 2:08 | https://www.youtube.com/watch?v=5zsBVm4qK_A |
| 14 | Time (Inception) | Hans Zimmer | Patrik Pietschmann | 4:24 | https://www.youtube.com/watch?v=b8HVQtIoBYU |
| 15 | He's a Pirate (Pirates of the Caribbean) | Klaus Badelt | Patrik Pietschmann | 3:00 | https://www.youtube.com/watch?v=2aBtDz87UK0 |
| 16 | Married Life (Up) | Michael Giacchino | kylelandry | 4:03 | https://www.youtube.com/watch?v=fnyEi4qeuAk |
| 17 | Mia & Sebastian's Theme (La La Land) | Justin Hurwitz | Luca Friesen | 1:40 | https://www.youtube.com/watch?v=5hwFiShs8cs |
| 18 | Sweden (Minecraft) | C418 | Piano Music Bros. | 2:12 | https://www.youtube.com/watch?v=7jFJbp8rYDA |
| 19 | Wet Hands (Minecraft) | C418 | Piano Music Bros. | 1:55 | https://www.youtube.com/watch?v=5Zor2EJNp5o |
| 20 | Megalovania (Undertale) | Toby Fox | Theishter - Anime on Piano | 4:08 | https://www.youtube.com/watch?v=SWKR0BzL_z0 |
| 21 | Rush E *(very dense: try --max-keys 6)* | Sheet Music Boss | Sheet Music Boss | 2:58 | https://www.youtube.com/watch?v=Qskm9MTz2V4 |

## Pop and viral hits

| # | Song | Artist | Piano version | Length | Link |
|---|---|---|---|---|---|
| 22 | Golden (KPop Demon Hunters) | HUNTR/X | Pianella Piano | 3:28 | https://www.youtube.com/watch?v=Wq3Y-C9IkSU |
| 23 | Soda Pop (KPop Demon Hunters) | Saja Boys | Sheet Music Boss | 2:35 | https://www.youtube.com/watch?v=bwXVHX60p7A |
| 24 | The Fate of Ophelia | Taylor Swift | Pianella Piano | 4:02 | https://www.youtube.com/watch?v=XmHkP6uakuo |
| 25 | Die With A Smile | Lady Gaga & Bruno Mars | Riyandi Kusuma | 4:27 | https://www.youtube.com/watch?v=IGhWoBfQWmQ |
| 26 | APT. | ROSÉ & Bruno Mars | Pianella Piano | 3:01 | https://www.youtube.com/watch?v=2HfDMiPpnh0 |
| 27 | Birds of a Feather | Billie Eilish | Pianella Piano | 3:46 | https://www.youtube.com/watch?v=Pmw0Bgw72OA |
| 28 | lovely | Billie Eilish & Khalid | Rousseau | 4:00 | https://www.youtube.com/watch?v=XhQq0aXhEos |
| 29 | Golden Hour | JVKE | Pianella Piano | 3:48 | https://www.youtube.com/watch?v=S8TvXhLtLa0 |
| 30 | Glimpse of Us | Joji | Pianella Piano | 4:08 | https://www.youtube.com/watch?v=5HgExMvlERg |
| 31 | Another Love | Tom Odell | PianoX | 4:15 | https://www.youtube.com/watch?v=ZuLbiwhehTo |
| 32 | Someone You Loved | Lewis Capaldi | Pianella Piano | 3:16 | https://www.youtube.com/watch?v=eT5muWj8rKI |
| 33 | Blinding Lights | The Weeknd | Pianella Piano | 3:19 | https://www.youtube.com/watch?v=nWis_uYXANk |
| 34 | Perfect | Ed Sheeran | Pianella Piano | 4:34 | https://www.youtube.com/watch?v=yr2cLuKJ2a8 |
| 35 | All of Me | John Legend | Rousseau | 5:16 | https://www.youtube.com/watch?v=b3E6E6hYSSI |
| 36 | A Thousand Years | Christina Perri | Riyandi Kusuma | 4:45 | https://www.youtube.com/watch?v=iZpZDivj6SU |
| 37 | Someone Like You | Adele | Pianella Piano | 4:58 | https://www.youtube.com/watch?v=z5pW-WSScNw |
| 38 | Until I Found You | Stephen Sanchez | Pianella Piano | 3:09 | https://www.youtube.com/watch?v=Q4uPCERm3bo |
| 39 | Ordinary | Alex Warren | Pianella Piano | 3:20 | https://www.youtube.com/watch?v=InkrcTXdW5w |
| 40 | Beautiful Things | Benson Boone | Pianella Piano | 3:15 | https://www.youtube.com/watch?v=XT4ktgVlbbw |
| 41 | Espresso | Sabrina Carpenter | Pianella Piano | 3:12 | https://www.youtube.com/watch?v=I2gMUHWAq3g |
| 42 | Running Up That Hill | Kate Bush | Brooklyn Duo | 3:57 | https://www.youtube.com/watch?v=DHkrnOjlf7Y |
| 43 | Arcade | Duncan Laurence | Pianella Piano | 3:22 | https://www.youtube.com/watch?v=JQdHj_CUKpg |
| 44 | Heat Waves | Glass Animals | Pianella Piano | 4:02 | https://www.youtube.com/watch?v=dHsQYTqKN4A |
| 45 | Let Her Go | Passenger | Pianella Piano | 4:26 | https://www.youtube.com/watch?v=4pgUj4P7fWk |
| 46 | Daylight | David Kushner | PianoX | 3:48 | https://www.youtube.com/watch?v=HlxMI1SAtg4 |
| 47 | Sweater Weather | The Neighbourhood | Gabriel Piano | 4:25 | https://www.youtube.com/watch?v=A24IXhDBJMg |
| 48 | I Wanna Be Yours | Arctic Monkeys | ThePianoKid | 3:22 | https://www.youtube.com/watch?v=tIwyBHLRCzs |
| 49 | Little Dark Age | MGMT | lensky.cover | 3:26 | https://www.youtube.com/watch?v=pwHWoY78Wns |
| 50 | apathy | øneheart | FMM Music | 1:50 | https://www.youtube.com/watch?v=l8feBj3ogUA |

## Anime, J-pop and K-drama

| # | Song | Artist | Piano version | Length | Link |
|---|---|---|---|---|---|
| 51 | IRIS OUT (Chainsaw Man: Reze Arc) | Kenshi Yonezu | Animenz Piano Sheets | 2:39 | https://www.youtube.com/watch?v=0_W4BwfRvkg |
| 52 | JANE DOE (Chainsaw Man: Reze Arc) | Kenshi Yonezu & Hikaru Utada | Animenz Piano Sheets | 4:55 | https://www.youtube.com/watch?v=LRHzcfLHUOw |
| 53 | Lemon | Kenshi Yonezu | marasy8 | 4:29 | https://www.youtube.com/watch?v=uKBUl07jBo0 |
| 54 | Unravel (Tokyo Ghoul) *(hard)* | TK from Ling tosite sigure | Animenz Piano Sheets | 4:08 | https://www.youtube.com/watch?v=sEQf5lcnj_o |
| 55 | Gurenge (Demon Slayer) *(hard)* | LiSA | Animenz Piano Sheets | 4:07 | https://www.youtube.com/watch?v=NQMmZ4Psb7w |
| 56 | Idol (Oshi no Ko) *(hard)* | YOASOBI | Animenz Piano Sheets | 3:49 | https://www.youtube.com/watch?v=lzSfnMp_DTs |
| 57 | Yoru ni Kakeru | YOASOBI | 深根 / Fukane | 4:37 | https://www.youtube.com/watch?v=8-_c0HDZI6E |
| 58 | Yuusha (Frieren) | YOASOBI | Ru's Piano Ru味春捲 | 3:30 | https://www.youtube.com/watch?v=fJ8hBV-FiGc |
| 59 | Sparkle (Your Name) | RADWIMPS | Animenz Piano Sheets | 6:35 | https://www.youtube.com/watch?v=cKgnDmpb4BU |
| 60 | Suzume (Suzume no Tojimari) | RADWIMPS | Torby Brand | 4:16 | https://www.youtube.com/watch?v=Gv61xS_-rUo |
| 61 | Hikaru Nara (Your Lie in April) | Goose house | Animenz Piano Sheets | 6:22 | https://www.youtube.com/watch?v=zsVAbS8xmaU |
| 62 | Blue Bird (Naruto Shippuden) | Ikimono-gakari | Animenz Piano Sheets | 4:28 | https://www.youtube.com/watch?v=FTrJ-J_lsr0 |
| 63 | Shinunoga E-Wa | Fujii Kaze | Pianilicia | 3:18 | https://www.youtube.com/watch?v=NvLWvIosReQ |
| 64 | Bling-Bang-Bang-Born (Mashle) | Creepy Nuts | よみぃ　Piano Yomii | 3:01 | https://www.youtube.com/watch?v=gyfNi8U5Cnw |
| 65 | Stay With Me (Goblin) | Chanyeol & Punch | Riyandi Kusuma | 3:31 | https://www.youtube.com/watch?v=DI21b6hjNVI |

## Edit songs: phonk, aura and slowed

| # | Song | Artist | Piano version | Length | Link |
|---|---|---|---|---|---|
| 66 | Metamorphosis | INTERWORLD | Jarel Gomes | 2:30 | https://www.youtube.com/watch?v=uQ15TOy6kn0 |
| 67 | Murder In My Mind | Kordhell | Jarel Gomes | 2:37 | https://www.youtube.com/watch?v=hDrEkmkKDKg |
| 68 | Close Eyes | DVRST | ThePianoKid | 2:30 | https://www.youtube.com/watch?v=ZKvHEzgmreY |
| 69 | RAVE | Dxrk ダーク | PianoX | 1:43 | https://www.youtube.com/watch?v=udTwR71zGWY |
| 70 | Sahara | Hensonn | FMM Music | 2:58 | https://www.youtube.com/watch?v=Lsn-fFoPwTg |
| 71 | Aura | Ogryzek | Anime Piano Tutorials | 2:02 | https://www.youtube.com/watch?v=a4f6SLiJ9TU |
| 72 | Override | KSLV Noh | Jarel Gomes | 2:20 | https://www.youtube.com/watch?v=0dKjanZ0hY8 |
| 73 | Neon Blade | MoonDeity | Jarel Gomes | 4:50 | https://www.youtube.com/watch?v=HsrjuXxfebM |
| 74 | Passo Bem Solto *(slowed version)* | ATLXS | Jova Musique - Pianella Piano | 2:06 | https://www.youtube.com/watch?v=_bwqHk7UVqs |
| 75 | Sigma Boy | Betsy & Mariya Yankovskaya | 정현주(Hyunjoo Jung) | 2:12 | https://www.youtube.com/watch?v=NrqqbhWdheg |
| 76 | Memory Reboot | VØJ & Narvent | Julian's Piano | 2:27 | https://www.youtube.com/watch?v=4p8VAvw95Nc |
| 77 | Fainted | Narvent | Grim Cat Piano | 4:00 | https://www.youtube.com/watch?v=aFRZRkE2NIU |
| 78 | Can You Feel My Heart (Gigachad) | Bring Me The Horizon | Sheet Music Boss | 3:51 | https://www.youtube.com/watch?v=3ZL8k78zSYo |
| 79 | After Dark | Mr.Kitty | Grim Cat Piano | 3:59 | https://www.youtube.com/watch?v=CeZW57CMgpo |
| 80 | The Perfect Girl | Mareux | ThePianoKid | 3:26 | https://www.youtube.com/watch?v=KWqqt90cYc0 |
| 81 | Hey Kids | Molina | FMM Music | 3:52 | https://www.youtube.com/watch?v=IL0eeSOsJtc |
| 82 | Living Life, In The Night | Cheriimoya & Sierra Kidd | Pianobar | 2:15 | https://www.youtube.com/watch?v=dQiclmH4I9U |
| 83 | Crystals | Isolate.exe | FMM Music | 2:28 | https://www.youtube.com/watch?v=49c-wMkBbtU |
| 84 | Resonance | HOME | Sheet Music Boss | 3:35 | https://www.youtube.com/watch?v=b7CWn2sDXTE |
| 85 | Gangsta's Paradise | Coolio | PianoX | 4:14 | https://www.youtube.com/watch?v=yXvouHaGa1w |
| 86 | Tokyo Drift | Teriyaki Boyz | Amosdoll Music | 1:55 | https://www.youtube.com/watch?v=Wep6QhUbGnY |

## TikTok, sad edits and aesthetic

| # | Song | Artist | Piano version | Length | Link |
|---|---|---|---|---|---|
| 87 | Dark Red | Steve Lacy | Piano Pop Tv | 2:56 | https://www.youtube.com/watch?v=JvT-eNO9bi0 |
| 88 | Mary on a Cross | Ghost | Connor Schröder | 3:33 | https://www.youtube.com/watch?v=dqeBNxgnNdM |
| 89 | Moonlight | XXXTENTACION | PianoX | 2:28 | https://www.youtube.com/watch?v=YyNDyFWnaPo |
| 90 | Space Song | Beach House | TutorialsByHugo | 5:34 | https://www.youtube.com/watch?v=mZ1axkMKz7U |
| 91 | Apocalypse | Cigarettes After Sex | Ipy’s Piano | 5:05 | https://www.youtube.com/watch?v=Fdz1CmjQz1c |
| 92 | K. | Cigarettes After Sex | ThePianoKid | 5:15 | https://www.youtube.com/watch?v=3gG90SEjqvQ |
| 93 | Way Down We Go | KALEO | Afafos Cover | 3:23 | https://www.youtube.com/watch?v=9nTDH0YG8LA |
| 94 | Romantic Homicide | d4vd | Gabriel Piano | 2:34 | https://www.youtube.com/watch?v=yaa4ay10DFY |
| 95 | Blue | yung kai | 정현주(Hyunjoo Jung) | 3:37 | https://www.youtube.com/watch?v=5v9qO37qp2U |
| 96 | Those Eyes | New West | TutorialsByHugo | 4:00 | https://www.youtube.com/watch?v=hE4e1Ez30_Q |
| 97 | Pretty Little Baby | Connie Francis | The Theorist | 2:25 | https://www.youtube.com/watch?v=T_JrdP_HBN8 |
| 98 | Line Without a Hook | Ricky Montgomery | PianoMix | 4:31 | https://www.youtube.com/watch?v=ykwSzdQ4t6s |
| 99 | I Love You So | The Walters | TutorialsByHugo | 2:58 | https://www.youtube.com/watch?v=VKnhqPa0wEM |
| 100 | Heather | Conan Gray | Gerard Chua | 4:13 | https://www.youtube.com/watch?v=21Jsm0N9riI |
| 101 | Sailor Song | Gigi Perez | Gabriel Piano | 3:23 | https://www.youtube.com/watch?v=1pI2bk1xw5E |
| 102 | Dandelions | Ruth B. | Jova Musique - Pianella Piano | 4:04 | https://www.youtube.com/watch?v=7fD8Z56kSP8 |
| 103 | My Love Mine All Mine | Mitski | Jova Musique - Pianella Piano | 2:28 | https://www.youtube.com/watch?v=CVWh-MFOwGE |
| 104 | Washing Machine Heart | Mitski | Kyokion | 2:10 | https://www.youtube.com/watch?v=vzaIUpB_ih8 |
| 105 | Chamber of Reflection | Mac DeMarco | Pablo Amoon | 3:40 | https://www.youtube.com/watch?v=MDSrOAIe6qc |
| 106 | Softcore | The Neighbourhood | PianoMix | 3:45 | https://www.youtube.com/watch?v=ne1s9HJEm2U |
| 107 | Lovers Rock | TV Girl | riiyawe | 2:40 | https://www.youtube.com/watch?v=zYki-z_vpoU |
| 108 | No Surprises | Radiohead | Coluscio | 3:43 | https://www.youtube.com/watch?v=Z_Qlo23fdAY |
| 109 | Rises the Moon | Liana Flores | yash | 2:09 | https://www.youtube.com/watch?v=8pSOJTQsFQ8 |
| 110 | WILDFLOWER | Billie Eilish | Jova Musique - Pianella Piano | 4:35 | https://www.youtube.com/watch?v=arZm8zmrs_Q |
| 111 | Sunflower (Spider-Verse) | Post Malone & Swae Lee | Rousseau | 3:32 | https://www.youtube.com/watch?v=Tve5DydxZ-Y |
| 112 | Plastic Love | Mariya Takeuchi | LotusFlower | 5:17 | https://www.youtube.com/watch?v=DOQyQ1meMlA |
| 113 | Mayonaka no Door (Stay With Me) | Miki Matsubara | MOON Sheet Music | 4:15 | https://www.youtube.com/watch?v=BGhC9gtcK_c |

## Film and TV edits

| # | Song | Artist | Piano version | Length | Link |
|---|---|---|---|---|---|
| 114 | Lux Aeterna (Requiem for a Dream) | Clint Mansell | Patrik Pietschmann | 4:07 | https://www.youtube.com/watch?v=C7Yjy5vASas |
| 115 | Can You Hear the Music (Oppenheimer) | Ludwig Göransson | Patrik Pietschmann | 2:07 | https://www.youtube.com/watch?v=D7awk7_vO0k |
| 116 | Something in the Way (The Batman) | Nirvana | AtinPiano | 4:15 | https://www.youtube.com/watch?v=-kAghaewp6g |
| 117 | Bloody Mary (Wednesday dance) *(sped-up version)* | Lady Gaga | PianoX | 3:18 | https://www.youtube.com/watch?v=-jD3ZF34xw4 |
| 118 | Enemy (Arcane) | Imagine Dragons & JID | Jova Musique - Pianella Piano | 3:07 | https://www.youtube.com/watch?v=Yu9ScEmulsU |
| 119 | Pink Soldiers (Squid Game) | 23 | Jova Musique - Pianella Piano | 2:48 | https://www.youtube.com/watch?v=s41gRh4l7L8 |
| 120 | Way Back Then (Squid Game) | Jung Jae-il | Grim Cat Piano | 2:30 | https://www.youtube.com/watch?v=6RVjPTNcdco |
| 121 | Gravity Falls Theme | Brad Breeck | ThePandaTooth | 2:01 | https://www.youtube.com/watch?v=htYA0hs5NoU |

## Memes

| # | Song | Artist | Piano version | Length | Link |
|---|---|---|---|---|---|
| 122 | Never Gonna Give You Up | Rick Astley | PianoX | 3:25 | https://www.youtube.com/watch?v=RmK_V1FHH-o |
| 123 | Astronomia (Coffin Dance) | Tony Igy & Vicetone | Jova Musique - Pianella Piano | 3:27 | https://www.youtube.com/watch?v=RHDrxL28XSI |
| 124 | Crab Rave | Noisestorm | Sheet Music Boss | 2:56 | https://www.youtube.com/watch?v=swuoGF0WwNQ |
| 125 | Chipi Chipi Chapa Chapa (Dubidubidu) | Christell | Sheet Music Boss | 3:44 | https://www.youtube.com/watch?v=cqAJW88_HyU |
| 126 | Nyan Cat | daniwell | Sheet Music Boss | 1:20 | https://www.youtube.com/watch?v=jr9MwdPTCrk |
| 127 | All Star | Smash Mouth | Sheet Music Boss | 3:34 | https://www.youtube.com/watch?v=X8dV8RHRnl4 |
| 128 | Sandstorm *(piano duet: dense, try Simplified)* | Darude | Sheet Music Boss | 4:03 | https://www.youtube.com/watch?v=CEPIN5PcioY |
| 129 | Ievan Polkka (Leekspin) | Loituma | Sheet Music Boss | 2:58 | https://www.youtube.com/watch?v=1JQv8SbDlwY |
| 130 | Caramelldansen | Caramella Girls | Sheet Music Boss | 3:16 | https://www.youtube.com/watch?v=pZwTEPalTtI |
| 131 | Dragostea Din Tei (Numa Numa) | O-Zone | Sheet Music Boss | 3:54 | https://www.youtube.com/watch?v=OorW_90Y5Dw |
| 132 | Giorno's Theme (JoJo) | Yugo Kanno | Rousseau | 5:18 | https://www.youtube.com/watch?v=NscXXbmAggI |
| 133 | Roundabout (To Be Continued) *(just the meme part)* | Yes | Sheet Music Boss | 0:54 | https://www.youtube.com/watch?v=yYHu-vZdBTc |
| 134 | Deja Vu (Initial D) | Dave Rodgers | Sheet Music Boss | 4:37 | https://www.youtube.com/watch?v=lpopZjhc11A |
| 135 | Running in the 90s (Initial D) | Max Coveri | Sheet Music Boss | 5:06 | https://www.youtube.com/watch?v=imfU-mdTDpg |
| 136 | Monkeys Spinning Monkeys | Kevin MacLeod | Sheet Music Boss | 2:14 | https://www.youtube.com/watch?v=3GxTSTynIfI |
| 137 | Kahoot Lobby Music | Kahoot! | Sheet Music Boss | 1:22 | https://www.youtube.com/watch?v=WpainqG-Tjg |
| 138 | Wii Shop Channel | Kazumi Totaka | Sheet Music Boss | 2:19 | https://www.youtube.com/watch?v=kHieZSAIQoY |
| 139 | Mii Channel | Kazumi Totaka | Sheet Music Boss | 2:16 | https://www.youtube.com/watch?v=qGPqRf6PTHI |
| 140 | Subway Surfers Theme | Kiloo | Sheet Music Boss | 2:33 | https://www.youtube.com/watch?v=eujL4L5WOz4 |
| 141 | Thick of It | KSI | Peter PlutaX | 2:56 | https://www.youtube.com/watch?v=_DkaoHClCXM |

## Anime edits

| # | Song | Artist | Piano version | Length | Link |
|---|---|---|---|---|---|
| 142 | Call of Silence (Attack on Titan) | Hiroyuki Sawano | PianoDeuss | 4:12 | https://www.youtube.com/watch?v=buZcLljh9eI |
| 143 | Vogel im Käfig (Attack on Titan) | Hiroyuki Sawano | PianoDeuss | 4:03 | https://www.youtube.com/watch?v=L8YIB2L6g3E |
| 144 | Akuma no Ko (Attack on Titan) *(hard)* | Ai Higuchi | Animenz Piano Sheets | 5:17 | https://www.youtube.com/watch?v=Td7uUVlB9bQ |
| 145 | KICK BACK (Chainsaw Man) *(hard)* | Kenshi Yonezu | Animenz Piano Sheets | 3:16 | https://www.youtube.com/watch?v=ub5dNHEagDA |
| 146 | Kaikai Kitan (Jujutsu Kaisen) | Eve | Fonzi M - Melodies on Piano | 2:57 | https://www.youtube.com/watch?v=pOAf4UoqFq0 |
| 147 | SPECIALZ (Jujutsu Kaisen) *(hard)* | King Gnu | Animenz Piano Sheets | 3:54 | https://www.youtube.com/watch?v=ptnAeX39DFI |
| 148 | Ao no Sumika (Jujutsu Kaisen) *(hard)* | Tatsuya Kitani | Animenz Piano Sheets | 3:29 | https://www.youtube.com/watch?v=iqct5A6C9JM |
| 149 | Otonoke (Dandadan) | Creepy Nuts | Anime Pro - Anime on Piano | 3:14 | https://www.youtube.com/watch?v=vBVsFJ8RrYk |
| 150 | LEveL (Solo Leveling) | SawanoHiroyuki[nZk] | Fonzi M - Melodies on Piano | 2:18 | https://www.youtube.com/watch?v=aNWd97OTDMM |
| 151 | L's Theme (Death Note) | Yoshihisa Hirano | F.B. Piano Anime | 2:31 | https://www.youtube.com/watch?v=mwOig9vNEhY |
| 152 | Sadness and Sorrow (Naruto) | Toshio Masuda | Patrik Pietschmann | 3:12 | https://www.youtube.com/watch?v=Kk60F8a7-Jw |
| 153 | You Say Run (My Hero Academia) | Yuki Hayashi | Fonzi M - Melodies on Piano | 4:22 | https://www.youtube.com/watch?v=Qnvc_ngnpvc |
| 154 | Ultra Instinct (Dragon Ball Super) | Norihito Sumitomo | GovzLegacy | 2:46 | https://www.youtube.com/watch?v=hfwV-sgmO20 |
| 155 | Kamado Tanjiro no Uta (Demon Slayer) | Go Shiina | PianiCast | 5:28 | https://www.youtube.com/watch?v=mNlxH0a6CfI |
| 156 | Mixed Nuts (Spy x Family) *(hard)* | Official HIGE DANdism | Animenz Piano Sheets | 3:43 | https://www.youtube.com/watch?v=81Ut3d4il-o |
| 157 | A Cruel Angel's Thesis (Evangelion) *(hard)* | Yoko Takahashi | Animenz Piano Sheets | 4:58 | https://www.youtube.com/watch?v=aYe-2Glruu4 |
| 158 | Departure! (Hunter x Hunter) *(hard)* | Masatoshi Ono | Animenz Piano Sheets | 5:38 | https://www.youtube.com/watch?v=acocwOhFJTw |
| 159 | Shikairo Days (My Deer Friend Nokotan) | Shika-bu | Ru's Piano Ru味春捲 | 4:03 | https://www.youtube.com/watch?v=9R1e-DMmqss |
| 160 | Lilium (Elfen Lied) | Konomi Suzuki | Myuu | 3:32 | https://www.youtube.com/watch?v=tdRzphj_-cE |
| 161 | Michishirube (Violet Evergarden) | Minori Chihara | Animenz Piano Sheets | 5:56 | https://www.youtube.com/watch?v=Vit_RIHhDMg |
| 162 | Nandemonaiya (Your Name) | RADWIMPS | PianiCast | 6:21 | https://www.youtube.com/watch?v=t3J2WU6j7wM |
| 163 | Path of the Wind (My Neighbor Totoro) | Joe Hisaishi | Piano Music Bros. | 3:33 | https://www.youtube.com/watch?v=asB23WeoyM0 |

## Vocaloid and internet music

| # | Song | Artist | Piano version | Length | Link |
|---|---|---|---|---|---|
| 164 | Mesmerizer | 32ki (Miku & Teto) | 으엨 희 / Uaaaaak | 2:36 | https://www.youtube.com/watch?v=F1yq_J7c6bM |
| 165 | Tetoris | Hiiragi Magnetite (Kasane Teto) | よみぃ　Piano Yomii | 2:30 | https://www.youtube.com/watch?v=F1o9AeXV2F8 |
| 166 | Rabbit Hole | DECO*27 | BelowAverage. | 2:41 | https://www.youtube.com/watch?v=di6gy0x8Rn4 |
| 167 | Senbonzakura | Kurousa-P | Piano Music Bros. | 4:09 | https://www.youtube.com/watch?v=OpNWT6a8n9U |
| 168 | Lagtrain | inabakumori | marasy8 | 4:24 | https://www.youtube.com/watch?v=VLPHUgLDnPY |
| 169 | Fukkireta (Ochame Kinou) | Lamaze-P (Kasane Teto) | Nanaki Piano | 4:16 | https://www.youtube.com/watch?v=lZYnD-kvupM |
| 170 | It's Been So Long (FNAF 2) | The Living Tombstone | Sheet Music Boss | 2:59 | https://www.youtube.com/watch?v=R2u4ETnYCgI |
| 171 | The Amazing Digital Circus Theme | Gooseworx | Sheet Music Boss | 2:01 | https://www.youtube.com/watch?v=AKkhopiZkN8 |
| 172 | Shelter | Porter Robinson & Madeon | Rousseau | 4:37 | https://www.youtube.com/watch?v=SB8IyvckpP8 |

## Game music

| # | Song | Artist | Piano version | Length | Link |
|---|---|---|---|---|---|
| 173 | His Theme (Undertale) | Toby Fox | Sheet Music Boss | 2:24 | https://www.youtube.com/watch?v=KR07b--LdUY |
| 174 | Hopes and Dreams (Undertale) | Toby Fox | Piano Music Bros. | 3:10 | https://www.youtube.com/watch?v=JWVV4VhvJ1c |
| 175 | Field of Hopes and Dreams (Deltarune) *(played by the official Piano Collections arranger)* | Toby Fox | Trevor Alan Gomes | 3:31 | https://www.youtube.com/watch?v=b1fcz31OCjw |
| 176 | City of Tears (Hollow Knight) *(official Piano Collections)* | Christopher Larkin | Materia Collective | 5:36 | https://www.youtube.com/watch?v=SB1rgO8jMZo |
| 177 | Resurrections (Celeste) *(official Piano Collections)* | Lena Raine | Materia Collective | 3:48 | https://www.youtube.com/watch?v=ia799l1tozQ |
| 178 | Subwoofer Lullaby (Minecraft) | C418 | Piano Music Bros. | 3:22 | https://www.youtube.com/watch?v=NDCRKNwzvA4 |
| 179 | Aria Math (Minecraft) | C418 | Pianicam | 3:00 | https://www.youtube.com/watch?v=_qK4wSzd3S8 |
| 180 | Lavender Town (Pokémon) | Junichi Masuda | Piano Music Bros. | 3:30 | https://www.youtube.com/watch?v=ljlyYMDxdxU |
| 181 | Song of Storms (Zelda) | Koji Kondo | Piano Music Bros. | 1:19 | https://www.youtube.com/watch?v=yvCEF5-7hwQ |
| 182 | Zelda's Lullaby | Koji Kondo | Piano Music Bros. | 2:36 | https://www.youtube.com/watch?v=90ZZYY98NPo |
| 183 | Hope Is the Thing With Feathers (Honkai: Star Rail) | Robin (Chevy) | ふぁろう | 2:48 | https://www.youtube.com/watch?v=ITPJgOhdKZI |
| 184 | Everything's Alright (To the Moon) | Laura Shigihara | kyukiemusic | 3:41 | https://www.youtube.com/watch?v=7gHnr8O7yVs |
| 185 | Tetris Theme (Korobeiniki) | traditional | Patrik Pietschmann | 3:07 | https://www.youtube.com/watch?v=Ci5squuWW3Q |
