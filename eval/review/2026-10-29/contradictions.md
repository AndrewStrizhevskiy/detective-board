# Contradiction cases: review sheet

Review kit of 2026-10-29 for issue #9, built by `scripts/eval/review_kit.py` (seed `gold-review-v1`).
Passages are from `data/clean/`; the quote is in bold. **The pre-check is a script, not a review.**
Write your verdict in `verdicts.csv` (see README.md).

## c002 · R1_place_conflict · test split · `abbey-grange`

**Question:** Where was Lady Brackenstall when Sir Eustace burst into the dining-room: tied to the chair or standing at the window?

**Expected finding:** `True` · evidence `explicit` · needs time normalisation `False`

**Expected description:** Lady Brackenstall says she was already bound to the oaken chair at the head of the table when her husband entered. Captain Crocker says she was standing with him just inside the window when Sir Eustace rushed in. She cannot be bound in the chair and standing at the window at the same moment; Holmes concludes she was put in the chair after the death.

**Author's note:** confidence=medium. Clean as a place conflict only once Crocker's confession is read; before that Holmes derives it from the blood mark.

**Claim 1:** Lady Brackenstall: already tied to the oaken chair at the head of the table · pre-check: verbatim, 1 place

> ...I flung the curtain aside and found myself face to face with a broad-shouldered elderly man, who had just stepped into the room. The window is a long French one, which really forms a door leading to the lawn. I held my bedroom candle lit in my hand, and, by its light, behind the first man I saw two others, who were in the act of entering. I stepped back, but the fellow was on me in an instant. He caught me first by the wrist and then by the throat. I opened my mouth to scream, but he struck me a savage blow with his fist over the eye, and felled me to the ground. I must have been unconscious for a few minutes, for when I came to myself, I found that they had torn down the bell-rope, and had **secured me tightly to the oaken chair which stands at the head of the dining-table**. I was so firmly bound that I could not move, and a handkerchief round my mouth prevented me from uttering a sound. It was at this instant that my unfortunate husband entered the room. He had evidently heard some suspicious sounds, and he came prepared for such a scene as he found. He was dressed in nightshirt and trousers, with his favourite blackthorn cudgel in his hand. He rushed at the burglars, but another—it was an elderly man—stooped, picked the poker out of the grate and struck him a horrible blow as he passed. He fell with a groan and never moved again. I fainted once more, but again it could only have been for a very few minutes during which I was insensible. When I opened my eyes...

**Claim 2:** Lady Brackenstall: husband entered after she was bound · pre-check: verbatim, 1 place

> ...the lawn. I held my bedroom candle lit in my hand, and, by its light, behind the first man I saw two others, who were in the act of entering. I stepped back, but the fellow was on me in an instant. He caught me first by the wrist and then by the throat. I opened my mouth to scream, but he struck me a savage blow with his fist over the eye, and felled me to the ground. I must have been unconscious for a few minutes, for when I came to myself, I found that they had torn down the bell-rope, and had secured me tightly to the oaken chair which stands at the head of the dining-table. I was so firmly bound that I could not move, and a handkerchief round my mouth prevented me from uttering a sound. **It was at this instant that my unfortunate husband entered the room.** He had evidently heard some suspicious sounds, and he came prepared for such a scene as he found. He was dressed in nightshirt and trousers, with his favourite blackthorn cudgel in his hand. He rushed at the burglars, but another—it was an elderly man—stooped, picked the poker out of the grate and struck him a horrible blow as he passed. He fell with a groan and never moved again. I fainted once more, but again it could only have been for a very few minutes during which I was insensible. When I opened my eyes I found that they had collected the silver from the sideboard, and they had drawn a bottle of wine which stood there. Each of them had a glass in his hand. I have already told you, hav...

**Claim 3:** Captain Crocker: she stood with him by the window when Sir Eustace came in · pre-check: verbatim, 1 place

> ... would see her once before I left. Theresa was always my friend, for she loved Mary and hated this villain almost as much as I did. From her I learned the ways of the house. Mary used to sit up reading in her own little room downstairs. I crept round there last night and scratched at the window. At first she would not open to me, but in her heart I know that now she loves me, and she could not leave me in the frosty night. She whispered to me to come round to the big front window, and I found it open before me, so as to let me into the dining-room. Again I heard from her own lips things that made my blood boil, and again I cursed this brute who mishandled the woman I loved. Well, gentlemen, **I was standing with her just inside the window, in all innocence, as God is my judge, when he rushed like a madman into the room**, called her the vilest name that a man could use to a woman, and welted her across the face with the stick he had in his hand. I had sprung for the poker, and it was a fair fight between us. See here, on my arm, where his first blow fell. Then it was my turn, and I went through him as if he had been a rotten pumpkin. Do you think I was sorry? Not I! It was his life or mine, but far more than that, it was his life or hers, for how could I leave her in the power of this madman? That was how I killed him. Was I wrong? Well, then, what would either of you gentlemen have done, if you had been in my position?

**Claim 4:** Sherlock Holmes: places her in the chair only after the death · pre-check: verbatim, 1 place

> “Undoubtedly it is blood. This alone puts the lady’s story out of court. If she were seated on the chair when the crime was done, how comes that mark? **No, no, she was placed in the chair _after_ the death of her husband.** I’ll wager that the black dress shows a corresponding mark to this. We have not yet met our Waterloo, Watson, but this is our Marengo, for it begins in defeat and ends in victory. I should like now to have a few words with the nurse, Theresa. We must be wary for a while, if we are to get the information which we want.”

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---

## c003 · R1_place_conflict · test split · `norwood-builder`

**Question:** Is McFarlane's account of spending the night at an hotel compatible with the thumb-mark in Oldacre's hall?

**Expected finding:** `True` · evidence `inferred` · needs time normalisation `False`

**Expected description:** McFarlane says he left through the French window and slept at the Anerley Arms; the housekeeper says his hat was left in the hall; Lestrade reads a blood thumb-print in the hall as McFarlane fetching his hat after the crime. On the evidence as presented, McFarlane is both away at the hotel and inside the hall after the crime. Holmes later shows the print was planted, so the conflict is in the evidence as presented, not in the truth.

**Author's note:** confidence=low. Borderline R1: the 'two places' are produced by contested evidence, and the text resolves it as a plant. Human decision needed on whether this counts as R1 or as R3.

**Claim 1:** McFarlane: left by the French window, spent the night at the Anerley Arms · pre-check: verbatim, 1 place

> “I will not be sure, but I believe that it was only half down. Yes, I remember how he pulled it up in order to swing open the window. I could not find my stick, and he said, ‘Never mind, my boy, I shall see a good deal of you now, I hope, and I will keep your stick until you come back to claim it.’ I left him there, the safe open, and the papers made up in packets upon the table. It was so late that I could not get back to Blackheath, **so I spent the night at the Anerley Arms**, and I knew nothing more until I read of this horrible affair in the morning.”

**Claim 2:** Mrs. Lexington: his hat and probably stick were left in the hall · pre-check: verbatim, 1 place

> “Finally, having drawn every other cover and picked up no scent, I tried my luck with the housekeeper. Mrs. Lexington is her name—a little, dark, silent person, with suspicious and sidelong eyes. She could tell us something if she would—I am convinced of it. But she was as close as wax. Yes, she had let Mr. McFarlane in at half-past nine. She wished her hand had withered before she had done so. She had gone to bed at half-past ten. Her room was at the other end of the house, and she could hear nothing of what had passed. **Mr. McFarlane had left his hat, and to the best of her belief his stick, in the hall.** She had been awakened by the alarm of fire. Her poor, dear master had certainly been murdered. Had he any enemies? Well, every man had enemies, but Mr. Oldacre kept himself very much to himself, and only met people in the way of business. She had seen the buttons, and was sure that they belonged to the clothes which he had worn last night. The wood-pile was very dry, for it had not rained for a month. It burned like tinder, and by the time she reached the spot, nothing could be seen but flames. She and all the firemen smelled the burned flesh from inside it. She knew nothing of the papers, nor of Mr. Oldacre’s private affairs.

**Claim 3:** Lestrade: reads the thumb-mark as McFarlane fetching his hat after the crime · pre-check: verbatim, 1 place

> “**This is where young McFarlane must have come out to get his hat after the crime was done**,” said he. “Now look at this.” With dramatic suddenness he struck a match, and by its light exposed a stain of blood upon the whitewashed wall. As he held the match nearer, I saw that it was more than a stain. It was the well-marked print of a thumb.

**Claim 4:** Sherlock Holmes: the mark was not there the day before · pre-check: verbatim, 1 place

> “**Only this: that I _know_ that that mark was not there when I examined the hall yesterday.** And now, Watson, let us have a little stroll round in the sunshine.”

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---

## c004 · R1_place_conflict · dev split · `reigate-squires`

**Question:** Where was Alec Cunningham when William Kirwan was shot, and does his account fit what Holmes establishes?

**Expected finding:** `True` · evidence `inferred` · needs time normalisation `False`

**Expected description:** Alec says he stood at the foot of the stairs inside the house and saw two strangers wrestling outside. Holmes shows the shot was fired from over four yards and that, if Alec's story were right, only Alec himself could have torn the paper from the dead man's hand, i.e. Alec was at the body rather than inside the house watching a stranger.

**Author's note:** confidence=low. Borderline R1: Holmes argues about sequence and distance, not about a stated alibi. Human decision needed.

**Claim 1:** Inspector (reporting Alec): Alec at the foot of the stairs saw two men wrestling outside · pre-check: verbatim, 1 place

> “Yes, sir. But he was off like a deer after the shot that killed poor William Kirwan was fired. Mr. Cunningham saw him from the bedroom window, and Mr. Alec Cunningham saw him from the back passage. It was quarter to twelve when the alarm broke out. Mr. Cunningham had just got into bed, and Mr. Alec was smoking a pipe in his dressing-gown. They both heard William the coachman calling for help, and Mr. Alec ran down to see what was the matter. The back door was open, and **as he came to the foot of the stairs he saw two men wrestling together outside**. One of them fired a shot, the other dropped, and the murderer rushed across the garden and over the hedge. Mr. Cunningham, looking out of his bedroom, saw the fellow as he gained the road, but lost sight of him at once. Mr. Alec stopped to see if he could help the dying man, and so the villain got clean away. Beyond the fact that he was a middle-sized man and dressed in some dark stuff, we have no personal clue; but we are making energetic inquiries, and if he is a stranger we shall soon find him out.”

**Claim 2:** Sherlock Holmes: if Alec is right, Alec himself must have taken the paper from the dead man · pre-check: verbatim, 1 place

> “Before going into this, I would draw your attention to the fact that, if Alec Cunningham’s narrative was correct, and if the assailant, after shooting William Kirwan, had _instantly_ fled, then it obviously could not be he who tore the paper from the dead man’s hand. But if it was not he, **it must have been Alec Cunningham himself, for by the time that the old man had descended several servants were upon the scene**. The point is a simple one, but the Inspector had overlooked it because he had started with the supposition that these county magnates had had nothing to do with the matter. Now, I make a point of never having any prejudices, and of following docilely wherever fact may lead me, and so, in the very first stage of the investigation, I found myself looking a little askance at the part which had been played by Mr. Alec Cunningham.

**Claim 3:** Sherlock Holmes: fired at over four yards, no powder-blackening · pre-check: verbatim, 1 place

> “Having got so far, my next step was, of course, to examine into the details of the crime, and to see how far they would help us. I went up to the house with the Inspector, and saw all that was to be seen. The wound upon the dead man was, as I was able to determine with absolute confidence, **fired from a revolver at the distance of something over four yards**. There was no powder-blackening on the clothes. Evidently, therefore, Alec Cunningham had lied when he said that the two men were struggling when the shot was fired. Again, both father and son agreed as to the place where the man escaped into the road. At that point, however, as it happens, there is a broadish ditch, moist at the bottom. As there were no indications of bootmarks about this ditch, I was absolutely sure not only that the Cunninghams had again lied, but that there had never been any unknown man upon the scene at all.

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---

## c006 · R2_order_cycle_or_inconsistency · dev split · `reigate-squires`

**Question:** Do the times given for the Cunningham alarm agree between the police account and Holmes's written statement?

**Expected finding:** `True` · evidence `explicit` · needs time normalisation `True`

**Expected description:** The inspector reports the alarm at a quarter to twelve; Holmes's written statement says a quarter to one on Tuesday morning. The text itself calls this a mistake ('It was at a quarter to twelve, as a matter of fact'), so the two times conflict even though the narrative explains it away as a slip.

**Author's note:** confidence=medium. The slip is deliberate on Holmes's part, but a rule layer reading the text cannot know that; the gold answer is that the two times conflict and the text flags it.

**Claim 1:** Inspector: alarm broke out at quarter to twelve · pre-check: verbatim, 1 place

> “Yes, sir. But he was off like a deer after the shot that killed poor William Kirwan was fired. Mr. Cunningham saw him from the bedroom window, and Mr. Alec Cunningham saw him from the back passage. **It was quarter to twelve when the alarm broke out.** Mr. Cunningham had just got into bed, and Mr. Alec was smoking a pipe in his dressing-gown. They both heard William the coachman calling for help, and Mr. Alec ran down to see what was the matter. The back door was open, and as he came to the foot of the stairs he saw two men wrestling together outside. One of them fired a shot, the other dropped, and the murderer rushed across the garden and over the hedge. Mr. Cunningham, looking out of his bedroom, saw the fellow as he gained the road, but lost sight of him at once. Mr. Alec stopped to see if he could help the dying man, and so the villain got clean away. Beyond the fact that he was a middle-sized man and dressed in some dark stuff, we h...

**Claim 2:** Holmes's written statement: says the attempt was at about a quarter to one · pre-check: verbatim, 1 place

> “You see you begin, ‘Whereas, **at about a quarter to one on Tuesday morning an attempt was made**,’ and so on. It was at a quarter to twelve, as a matter of fact.”

**Claim 3:** Old Mr. Cunningham: corrects the mistake: it was a quarter to twelve · pre-check: verbatim, 1 place

> “You see you begin, ‘Whereas, at about a quarter to one on Tuesday morning an attempt was made,’ and so on. **It was at a quarter to twelve, as a matter of fact.**”

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---

## c007 · R2_order_cycle_or_inconsistency · dev split · `boscombe-valley-mystery`

**Question:** Does James McCarthy's account of when his father left the house fit the time given for the father's departure?

**Expected finding:** `True` · evidence `inferred` · needs time normalisation `True`

**Expected description:** James says he returned on the morning of Monday the 3rd and, shortly after his return, saw his father get out of the trap and walk rapidly out of the yard. The police account says McCarthy left his house about three in the afternoon, after being out at Ross in the morning. 'Shortly after' a morning return does not obviously fit a three o'clock departure.

**Author's note:** confidence=low. 'Morning' may be loose and no one in the text flags it. This is the weakest positive in the file; consider moving it to controls after human review.

**Claim 1:** James McCarthy: returned on the morning of Monday the 3rd · pre-check: verbatim, 1 place

> “Mr. James McCarthy, the only son of the deceased, was then called and gave evidence as follows: ‘I had been away from home for three days at Bristol, and **had only just returned upon the morning of last Monday, the 3rd**. My father was absent from home at the time of my arrival, and I was informed by the maid that he had driven over to Ross with John Cobb, the groom. Shortly after my return I heard the wheels of his trap in the yard, and, looking out of my window, I saw him get out and walk rapidly out of the yard, though I was not aware in which direction he was going. I then took my gun and strolled out in the direction of the Boscombe Pool, with the intention of visiting the rabbit warren which is upon the other side. On my way I saw William Crowder, the game-keeper, as he had stated in his evidence; but he is mistaken in thinking that I was following my father. I had no idea that he was in front of me. ...

**Claim 2:** James McCarthy: shortly after returning he saw his father leave the yard · pre-check: verbatim, 1 place

> “Mr. James McCarthy, the only son of the deceased, was then called and gave evidence as follows: ‘I had been away from home for three days at Bristol, and had only just returned upon the morning of last Monday, the 3rd. My father was absent from home at the time of my arrival, and I was informed by the maid that he had driven over to Ross with John Cobb, the groom. **Shortly after my return I heard the wheels of his trap in the yard**, and, looking out of my window, I saw him get out and walk rapidly out of the yard, though I was not aware in which direction he was going. I then took my gun and strolled out in the direction of the Boscombe Pool, with the intention of visiting the rabbit warren which is upon the other side. On my way I saw William Crowder, the game-keeper, as he had stated in his evidence; but he is mistaken in thinking that I was following my father. I had no idea that he was in front of me. When about a hundred yards from the pool I heard a cry of “Cooee!” which was a usual signal between my father and myself. I then hurried forward, and found him standing by the pool. He appeared to be much surprised a...

**Claim 3:** Holmes (summarising police facts): father left Hatherley about three in the afternoon · pre-check: verbatim, 1 place

> “On June 3rd, that is, on Monday last, **McCarthy left his house at Hatherley about three in the afternoon** and walked down to the Boscombe Pool, which is a small lake formed by the spreading out of the stream which runs down the Boscombe Valley. He had been out with his serving-man in the morning at Ross, and he had told the man that he must hurry, as he had an appointment of importance to keep at three. From that appointment he never came back alive.

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---

## c017 · R3_claim_vs_fact · test split · `blue-carbuncle`

**Question:** Is the name 'John Robinson' that the little man gives consistent with who he really is?

**Expected finding:** `True` · evidence `explicit` · needs time normalisation `False`

**Expected description:** The man first gives his name as John Robinson. Holmes insists on the real name and he admits he is James Ryder, the head attendant at the Hotel Cosmopolitan.

**Author's note:** confidence=medium. Trivial and low value; kept as a cheap R3 sanity case. The first quote includes the closing curly quote of the source.

**Claim 1:** the little man: gives the name John Robinson · pre-check: verbatim, 1 place

> The man hesitated for an instant. “My name is **John Robinson,” he answered with a sidelong glance.**

**Claim 2:** James Ryder: admits his real name · pre-check: verbatim, 1 place

> A flush sprang to the white cheeks of the stranger. “Well then,” said he, “**my real name is James Ryder**.”

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---

## c018 · R3_claim_vs_fact · dev split · `silver-blaze`

**Question:** Is the stable-lad's certainty that the stranger at the window drugged his supper compatible with Holmes's reasoning about the curried mutton?

**Expected finding:** `True` · evidence `inferred` · needs time normalisation `False`

**Expected description:** Hunter was certain the stranger drugged his curried mutton at the window. Holmes argues the stranger could not have caused curry to be served that night, so only Straker or his wife could have chosen the dish; the claim is not supported.

**Author's note:** confidence=medium. Holmes's inference, not an observed fact. Overlaps g038.

**Claim 1:** Ned Hunter: certain the stranger drugged his mutton at the window · pre-check: verbatim, 1 place

> “Hunter, on recovering from his stupor, was also quite positive as to the ownership of the cravat. **He was equally certain that the same stranger had, while standing at the window, drugged his curried mutton**, and so deprived the stables of their watchman.

**Claim 2:** Sherlock Holmes: Simpson could not have caused curry to be served · pre-check: verbatim, 1 place

> “It was the first link in my chain of reasoning. Powdered opium is by no means tasteless. The flavour is not disagreeable, but it is perceptible. Were it mixed with any ordinary dish the eater would undoubtedly detect it, and would probably eat no more. A curry was exactly the medium which would disguise this taste. **By no possible supposition could this stranger, Fitzroy Simpson, have caused curry to be served in the trainer’s family that night**, and it is surely too monstrous a coincidence to suppose that he happened to come along with powdered opium upon the very night when a dish happened to be served which would disguise the flavour. That is unthinkable. Therefore Simpson becomes eliminated from the case, and our attention centres upon Straker and his wife, the only two people who could have chosen curried mutton for supper that night. The opium was added after the dish was set aside for the stable-boy, for the others had the same for supper with no ill effects. Which of them, then, had access to that dish without the maid seeing them?

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---

## c024 · R3_claim_vs_fact · test split · `copper-beeches`

**Question:** Is the report that Alice Rucastle went to America consistent with what the Tollers say about her?

**Expected finding:** `True` · evidence `inferred` · needs time normalisation `False`

**Expected description:** Holmes recalls that the daughter 'was said to have gone to America'. Mrs. Toller then says Rucastle worried her until she got brain-fever and kept her confined in the house to keep Mr. Fowler away.

**Author's note:** confidence=medium. I did not read the passage where the 'America' story is first told to Miss Hunter; here it is only Holmes's paraphrase.

**Claim 1:** Sherlock Holmes: Alice was said to have gone to America · pre-check: verbatim, 1 place

> “Excellent! We shall then look thoroughly into the affair. Of course there is only one feasible explanation. You have been brought there to personate someone, and the real person is imprisoned in this chamber. That is obvious. As to who this prisoner is, I have no doubt that it is the daughter, Miss Alice Rucastle, if I remember right, **who was said to have gone to America**. You were chosen, doubtless, as resembling her in height, figure, and the colour of your hair. Hers had been cut off, very possibly in some illness through which she has passed, and so, of course, yours had to be sacrificed also. By a curious chance you came upon her tresses. The man in the road was undoubtedly some friend of hers—possibly her _fiancé_—and no doubt, as you wore the girl’s dress and were so like her, he was convinced from your laughter, whenever he saw you, and afterwards from your gesture, that Miss Rucastle was perfectly happy, and that she no longer desired his attentions. The dog is let loose at night to prevent him from endeavouring to communicate with her. So much is f...

**Claim 2:** Mrs. Toller: her father pressed her until she fell ill · pre-check: verbatim, 1 place

> ...wasn’t, from the time that her father married again. She was slighted like and had no say in anything, but it never really became bad for her until after she met Mr. Fowler at a friend’s house. As well as I could learn, Miss Alice had rights of her own by will, but she was so quiet and patient, she was, that she never said a word about them but just left everything in Mr. Rucastle’s hands. He knew he was safe with her; but when there was a chance of a husband coming forward, who would ask for all that the law would give him, then her father thought it time to put a stop on it. He wanted her to sign a paper, so that whether she married or not, he could use her money. When she wouldn’t do it, **he kept on worrying her until she got brain-fever**, and for six weeks was at death’s door. Then she got better at last, all worn to a shadow, and with her beautiful hair cut off; but that didn’t make no change in her young man, and he stuck to her as true as man could be.”

**Claim 3:** Sherlock Holmes: confirms the imprisonment · pre-check: verbatim, 1 place

> “Ah,” said Holmes, “I think that what you have been good enough to tell us makes the matter fairly clear, and that I can deduce all that remains. **Mr. Rucastle then, I presume, took to this system of imprisonment?**”

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---

## c025 · R3_claim_vs_fact · dev split · `boscombe-valley-mystery`

**Question:** Is James McCarthy's account of the 'Cooee' call consistent with what his father knew?

**Expected finding:** `True` · evidence `explicit` · needs time normalisation `False`

**Expected description:** James says he heard a 'Cooee' that was their usual signal between father and son, but the coroner points out the father uttered it before he saw James and before he knew James had returned from Bristol. Holmes later treats this as the key sign that the call was meant for someone else.

**Author's note:** confidence=medium. The conflict is between James's reading of the call and the father's state of knowledge. Overlaps g028.

**Claim 1:** James McCarthy: heard 'Cooee', a usual signal between father and son · pre-check: verbatim, 1 place

> ...ime of my arrival, and I was informed by the maid that he had driven over to Ross with John Cobb, the groom. Shortly after my return I heard the wheels of his trap in the yard, and, looking out of my window, I saw him get out and walk rapidly out of the yard, though I was not aware in which direction he was going. I then took my gun and strolled out in the direction of the Boscombe Pool, with the intention of visiting the rabbit warren which is upon the other side. On my way I saw William Crowder, the game-keeper, as he had stated in his evidence; but he is mistaken in thinking that I was following my father. I had no idea that he was in front of me. When about a hundred yards from the pool **I heard a cry of “Cooee!” which was a usual signal between my father and myself.** I then hurried forward, and found him standing by the pool. He appeared to be much surprised at seeing me and asked me rather roughly what I was doing there. A conversation ensued which led to high words and almost to blows, for my father was a man of a very violent temper. Seeing that his passion was becoming ungovernable, I left him and returned towards Hatherley Farm. I had not gone more than 150 yards, however, when I heard a hideous outcry behind me, which caused me to run back again. I found my father expiring upon the ground, with his head terribly injured. I dropped my gun and held him in my arms, but he almost instantly expired. I knelt beside him for some minutes, and then made my...

**Claim 2:** Coroner: father uttered it before seeing him or knowing he was back · pre-check: verbatim, 1 place

> “The Coroner: **How was it, then, that he uttered it before he saw you, and before he even knew that you had returned from Bristol?**

**Claim 3:** Sherlock Holmes: same point as a crucial fact · pre-check: verbatim, 1 place

> “Ah! who? I would call your attention very particularly to two points. One is that the murdered man had an appointment with someone at the pool, and that the someone could not have been his son, for his son was away, and he did not know when he would return. The second is that **the murdered man was heard to cry ‘Cooee!’ before he knew that his son had returned**. Those are the crucial points upon which the case depends. And now let us talk about George Meredith, if you please, and we shall leave all minor matters until to-morrow.”

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---

## c026 · R3_claim_vs_fact · test split · `black-peter`

**Question:** Is John Hopley Neligan's statement that he had not been at the hut before last night compatible with the notebook?

**Expected finding:** `True` · evidence `inferred` · needs time normalisation `False`

**Expected description:** Neligan answers 'No' when asked if he had been at the hut before last night, but Hopkins holds a notebook with Neligan's initials and a blood-stain found in the hut, and Neligan can only say he thought he had lost it at the hotel.

**Author's note:** confidence=medium. Holmes later shows Neligan did not kill Carey, but the text never says how the notebook reached the hut, so the claim-vs-notebook conflict stands. Overlaps g033.

**Claim 1:** Stanley Hopkins: asks whether he was there before last night · pre-check: verbatim, 1 place

> “**You have not been here before last night?**”

**Claim 2:** Stanley Hopkins: notebook with the prisoner's initials and blood-stain · pre-check: verbatim, 1 place

> “Then how do you account for _that_?” cried Hopkins, as he held up the damning notebook, **with the initials of our prisoner on the first leaf and the blood-stain on the cover**.

**Claim 3:** John Hopley Neligan: can only say he thought he had lost it at the hotel · pre-check: verbatim, 1 place

> “Where did you get it?” he groaned. “**I did not know. I thought I had lost it at the hotel.**”

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---

## c028 · consistent_control · dev split · `silver-blaze`

**Question:** Straker's overcoat is described as flapping from a furze-bush, yet there was no wind. Is that a contradiction?

**Expected finding:** `False` · evidence `inferred` · needs time normalisation `False`

**Expected description:** No. Holmes uses it as a clue: with no wind the coat was not blown against the bush but laid across it by someone.

**Author's note:** confidence=low. 'Flapping' is narrative colour; a strict reader may call it a small slip in the source. Human check advised.

**Claim 1:** Holmes (narrating): overcoat flapping from a furze-bush · pre-check: verbatim, 1 place

> “About a quarter of a mile from the stables **John Straker’s overcoat was flapping from a furze-bush.** Immediately beyond there was a bowl-shaped depression in the moor, and at the bottom of this was found the dead body of the unfortunate trainer. His head had been shattered by a savage blow from some heavy weapon, and he was wounded on the thigh, where there was a long, clean cut, inflicted evidently by some very sharp instrument. It was clear, however, that Straker had defended himself vigorously against his assailants, for in his right hand he held a small knife, which was clotted with blood up to the handle, while in his left he clasped a red and black silk cravat, which was recognised by the maid as having been worn on the preceding evening by the stranger who had visited the stables.

**Claim 2:** Inspector Gregory: no wind that night, very heavy rain · pre-check: verbatim, 1 place

> “**None; but very heavy rain.**”

**Claim 3:** Sherlock Holmes: therefore the coat was placed there · pre-check: verbatim, 1 place

> “**In that case the overcoat was not blown against the furze-bush, but placed there.**”

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---

## c033 · consistent_control · dev split · `abbey-grange`

**Question:** Lady Brackenstall says she has been married about a year, while her maid arrived eighteen months ago. Is that a contradiction?

**Expected finding:** `False` · evidence `inferred` · needs time normalisation `True`

**Expected description:** No. They arrived in England eighteen months ago and the marriage came later: the maid says they met him a month after arriving and married the following January.

**Author's note:** confidence=medium. Requires reading 'about a year' loosely and 'last year' without the story's date, which the text does not state.

**Claim 1:** Lady Brackenstall: married about a year · pre-check: verbatim, 1 place

> “I am the wife of Sir Eustace Brackenstall. **I have been married about a year.** I suppose that it is no use my attempting to conceal that our marriage has not been a happy one. I fear that all our neighbours would tell you that, even if I were to attempt to deny it. Perhaps the fault may be partly mine. I was brought up in the freer, less conventional atmosphere of South Australia, and this English life, with its proprieties and its primness, is not congenial to me. But the main reason lies in the one fact, which is notorious to everyone, and that is that Sir Eustace was a confirmed drunkard. To be with such a man for an hour is unpleasant. Can you imagine what it means for a sensitive and high-spirited woman to be tied to him for day and night? It is a sacrilege, a cr...

**Claim 2:** Inspector Hopkins: came to England eighteen months ago · pre-check: verbatim, 1 place

> “She has been with her all her life,” said Hopkins. “Nursed her as a baby, and **came with her to England when they first left Australia, eighteen months ago**. Theresa Wright is her name, and the kind of maid you don’t pick up nowadays. This way, Mr. Holmes, if you please!”

**Claim 3:** Theresa Wright: married in January of last year · pre-check: verbatim, 1 place

> ...ose marks on her arm that you saw this morning, but I know very well that they come from a stab with a hatpin. The sly devil—God forgive me that I should speak of him so, now that he is dead! But a devil he was, if ever one walked the earth. He was all honey when first we met him—only eighteen months ago, and we both feel as if it were eighteen years. She had only just arrived in London. Yes, it was her first voyage—she had never been from home before. He won her with his title and his money and his false London ways. If she made a mistake she has paid for it, if ever a woman did. What month did we meet him? Well, I tell you it was just after we arrived. We arrived in June, and it was July. **They were married in January of last year.** Yes, she is down in the morning-room again, and I have no doubt she will see you, but you must not ask too much of her, for she has gone through all that flesh and blood will stand.”

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---

## c038 · consistent_control · test split · `man-with-the-twisted-lip`

**Question:** St. Clair told his wife he was going into town to run errands, yet she sees him at a window in Swandam Lane at 4:35. Is that a contradiction?

**Expected finding:** `False` · evidence `inferred` · needs time normalisation `True`

**Expected description:** No. Swandam Lane is in the City, near the shipping company office where her telegram sent her; being there fits a day in town.

**Author's note:** confidence=medium. The 'contradiction' a naive reader sees is only that a respectable man is in an opium den; the text gives no timing conflict.

**Claim 1:** Sherlock Holmes: St. Clair went into town for two commissions · pre-check: verbatim, 1 place

> “**Last Monday Mr. Neville St. Clair went into town rather earlier than usual, remarking before he started that he had two important commissions to perform**, and that he would bring his little boy home a box of bricks. Now, by the merest chance, his wife received a telegram upon this same Monday, very shortly after his departure, to the effect that a small parcel of considerable value which she had been expecting was waiting for her at the offices of the Aberdeen Shipping Company. Now, if you are well up in your London, you will know that the office of the company is in Fresno Street, which branches out of Upper Swandam Lane, where you found me to-night. Mrs. St. Clair had her lunch, started for the City, did some shopping, proceeded to the company’s office, got her packet, and found herself at exactly 4:35 walking through Swandam Lane on her w...

**Claim 2:** Sherlock Holmes: Mrs. St. Clair walking through Swandam Lane at 4:35 · pre-check: verbatim, 1 place

> ... before he started that he had two important commissions to perform, and that he would bring his little boy home a box of bricks. Now, by the merest chance, his wife received a telegram upon this same Monday, very shortly after his departure, to the effect that a small parcel of considerable value which she had been expecting was waiting for her at the offices of the Aberdeen Shipping Company. Now, if you are well up in your London, you will know that the office of the company is in Fresno Street, which branches out of Upper Swandam Lane, where you found me to-night. Mrs. St. Clair had her lunch, started for the City, did some shopping, proceeded to the company’s office, got her packet, and **found herself at exactly 4:35 walking through Swandam Lane on her way back to the station**. Have you followed me so far?”

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---

## c041 · consistent_control · dev split · `boscombe-valley-mystery`

**Question:** Holmes says the father was at Ross in the morning with his man; James says he drove to Ross with Cobb the groom. Is that a contradiction?

**Expected finding:** `False` · evidence `explicit` · needs time normalisation `False`

**Expected description:** No. Both say the father went to Ross with a servant; John Cobb is the groom ('serving-man').

**Author's note:** confidence=medium. It is slightly inferential that 'serving-man' and 'groom' are the same person; the text does not equate them.

**Claim 1:** Holmes (summarising police facts): father was at Ross in the morning with his serving-man · pre-check: verbatim, 1 place

> “On June 3rd, that is, on Monday last, McCarthy left his house at Hatherley about three in the afternoon and walked down to the Boscombe Pool, which is a small lake formed by the spreading out of the stream which runs down the Boscombe Valley. **He had been out with his serving-man in the morning at Ross**, and he had told the man that he must hurry, as he had an appointment of importance to keep at three. From that appointment he never came back alive.

**Claim 2:** James McCarthy: father drove to Ross with John Cobb, the groom · pre-check: verbatim, 1 place

> “Mr. James McCarthy, the only son of the deceased, was then called and gave evidence as follows: ‘I had been away from home for three days at Bristol, and had only just returned upon the morning of last Monday, the 3rd. My father was absent from home at the time of my arrival, and I was informed by the maid that **he had driven over to Ross with John Cobb, the groom**. Shortly after my return I heard the wheels of his trap in the yard, and, looking out of my window, I saw him get out and walk rapidly out of the yard, though I was not aware in which direction he was going. I then took my gun and strolled out in the direction of the Boscombe Pool, with the intention of visiting the rabbit warren which is upon the other side. On my way I saw William Crowder, the game-keeper, as he had stated in his evidence; but he is mistaken in thinking that I was following my father. I had no idea that he was in front of me. When about a hundred yards from the pool I heard a cry of “Cooee!” which was a usual signal between my father and myself. I then hurried forward, an...

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---

## c042 · consistent_control · test split · `boscombe-valley-mystery`

**Question:** The game-keeper thought James was following his father; James says he did not know his father was ahead. Is that a contradiction in what happened?

**Expected finding:** `False` · evidence `inferred` · needs time normalisation `False`

**Expected description:** Not a conflict of observed facts. Both agree James went the same way with a gun a few minutes after his father; they differ only on whether he was deliberately following, which Crowder phrases as his belief.

**Author's note:** confidence=low. Disagrees in spirit with g027, which treats this as a conflict between accounts. Whether an inference-vs-denial counts as a contradiction is a labelling decision a human must make.

**Claim 1:** William Crowder: saw James going the same way with a gun · pre-check: verbatim, 1 place

> “From Hatherley Farmhouse to the Boscombe Pool is a quarter of a mile, and two people saw him as he passed over this ground. One was an old woman, whose name is not mentioned, and the other was William Crowder, a game-keeper in the employ of Mr. Turner. Both these witnesses depose that Mr. McCarthy was walking alone. The game-keeper adds that within a few minutes of his seeing Mr. McCarthy pass he had seen his son, Mr. James McCarthy, **going the same way with a gun under his arm**. To the best of his belief, the father was actually in sight at the time, and the son was following him. He thought no more of the matter until he heard in the evening of the tragedy that had occurred.

**Claim 2:** William Crowder: believes the son was following · pre-check: verbatim, 1 place

> “From Hatherley Farmhouse to the Boscombe Pool is a quarter of a mile, and two people saw him as he passed over this ground. One was an old woman, whose name is not mentioned, and the other was William Crowder, a game-keeper in the employ of Mr. Turner. Both these witnesses depose that Mr. McCarthy was walking alone. The game-keeper adds that within a few minutes of his seeing Mr. McCarthy pass he had seen his son, Mr. James McCarthy, going the same way with a gun under his arm. **To the best of his belief, the father was actually in sight at the time, and the son was following him.** He thought no more of the matter until he heard in the evening of the tragedy that had occurred.

**Claim 3:** James McCarthy: did not know his father was in front · pre-check: verbatim, 1 place

> ... from home for three days at Bristol, and had only just returned upon the morning of last Monday, the 3rd. My father was absent from home at the time of my arrival, and I was informed by the maid that he had driven over to Ross with John Cobb, the groom. Shortly after my return I heard the wheels of his trap in the yard, and, looking out of my window, I saw him get out and walk rapidly out of the yard, though I was not aware in which direction he was going. I then took my gun and strolled out in the direction of the Boscombe Pool, with the intention of visiting the rabbit warren which is upon the other side. On my way I saw William Crowder, the game-keeper, as he had stated in his evidence; **but he is mistaken in thinking that I was following my father**. I had no idea that he was in front of me. When about a hundred yards from the pool I heard a cry of “Cooee!” which was a usual signal between my father and myself. I then hurried forward, and found him standing by the pool. He appeared to be much surprised at seeing me and asked me rather roughly what I was doing there. A conversation ensued which led to high words and almost to blows, for my father was a man of a very violent temper. Seeing that his passion was becoming ungovernable, I left him and returned towards Hatherley Farm. I had not gone more than 150 yards, however, when I heard a hideous outcry behind me, which caused me to run back again. I found my father expiring upon the gro...

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---

## c043 · consistent_control · test split · `crooked-man`

**Question:** Do the evening times in the Barclay case (meeting at eight, home at a quarter past nine, Miss Morrison's quarter to nine) agree?

**Expected finding:** `False` · evidence `inferred` · needs time normalisation `True`

**Expected description:** They are compatible as approximate times: the meeting lasts forty minutes from eight, the ladies are in Hudson Street about a quarter to nine, stop to speak with Wood, and Mrs. Barclay is home at a quarter past nine.

**Author's note:** confidence=low. About half an hour of the walk home is not accounted for in the text, and Holmes later says 'that hour and a half' for 7:30 to 9:00. A human may judge this an R2 positive instead.

**Claim 1:** narrator (Holmes): meeting at eight, lasting forty minutes · pre-check: verbatim, 1 place

> “Mrs. Barclay was, it appears, a member of the Roman Catholic Church, and had interested herself very much in the establishment of the Guild of St. George, which was formed in connection with the Watt Street Chapel for the purpose of supplying the poor with cast-off clothing. **A meeting of the Guild had been held that evening at eight**, and Mrs. Barclay had hurried over her dinner in order to be present at it. When leaving the house she was heard by the coachman to make some commonplace remark to her husband, and to assure him that she would be back before very long. She then called for Miss Morrison, a young lady who lives in the next villa, and the two went off together to their meeting. It lasted forty minutes, and at a quarter-past nine Mrs. Barclay returned home, having left Miss Morrison at her door as she passed.

**Claim 2:** narrator (Holmes): Mrs. Barclay home at a quarter past nine · pre-check: verbatim, 1 place

> ...ars, a member of the Roman Catholic Church, and had interested herself very much in the establishment of the Guild of St. George, which was formed in connection with the Watt Street Chapel for the purpose of supplying the poor with cast-off clothing. A meeting of the Guild had been held that evening at eight, and Mrs. Barclay had hurried over her dinner in order to be present at it. When leaving the house she was heard by the coachman to make some commonplace remark to her husband, and to assure him that she would be back before very long. She then called for Miss Morrison, a young lady who lives in the next villa, and the two went off together to their meeting. It lasted forty minutes, and **at a quarter-past nine Mrs. Barclay returned home**, having left Miss Morrison at her door as she passed.

**Claim 3:** Miss Morrison: on the road about a quarter to nine · pre-check: verbatim, 1 place

> “‘**We were returning from the Watt Street Mission about a quarter to nine o’clock.** On our way we had to pass through Hudson Street, which is a very quiet thoroughfare. There is only one lamp in it, upon the left-hand side, and as we approached this lamp I saw a man coming towards us with his back very bent, and something like a box slung over one of his shoulders. He appeared to be deformed, for he carried his head low and walked with his knees bent. We were passing him when he raised his face to look at us in the circle of light thrown by the lamp, and as he did so he stopped and screamed out in a dreadful voice, “My God, it’s Nancy!” Mrs. Barclay turned as white as death, and would have fallen down had the dreadful-looking creature not caught hold of her. I was going to...

Check: (1) each quote says what its line says, and the speaker is right; (2) the finding
(conflict or not) follows from the quotes; (3) the kind (R1/R2/R3/control) fits; (4) not stronger than the text.

---
