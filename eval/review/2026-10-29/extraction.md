# Extraction gold: review sheet

Review kit of 2026-10-29 for issue #9, built by `scripts/eval/review_kit.py` (seed `gold-review-v1`).
The text is the chunk's own `text` field in `eval/extraction_gold/`; quotes are listed under it. **The pre-check is a script, not a review.**
Write your verdict in `verdicts.csv` (see README.md). This sheet is a snapshot of the
files on that date; after fixes the files, not the sheet, are what counts.

## boscombe-valley-mystery-0007 (`boscombe-valley-mystery`)

Chunk text:

> “Mr. James McCarthy, the only son of the deceased, was then called and gave evidence as follows: ‘I had been away from home for three days at Bristol, and had only just returned upon the morning of last Monday, the 3rd. My father was absent from home at the time of my arrival, and I was informed by the maid that he had driven over to Ross with John Cobb, the groom. Shortly after my return I heard the wheels of his trap in the yard, and, looking out of my window, I saw him get out and walk rapidly out of the yard, though I was not aware in which direction he was going. I then took my gun and strolled out in the direction of the Boscombe Pool, with the intention of visiting the rabbit warren which is upon the other side. On my way I saw William Crowder, the game-keeper, as he had stated in his evidence; but he is mistaken in thinking that I was following my father. I had no idea that he was in front of me. When about a hundred yards from the pool I heard a cry of “Cooee!” which was a usual signal between my father and myself. I then hurried forward, and found him standing by the pool. He appeared to be much surprised at seeing me and asked me rather roughly what I was doing there. A conversation ensued which led to high words and almost to blows, for my father was a man of a very violent temper. Seeing that his passion was becoming ungovernable, I left him and returned towards Hatherley Farm. I had not gone more than 150 yards, however, when I heard a hideous outcry behind me, which caused me to run back again. I found my father expiring upon the ground, with his head terribly injured. I dropped my gun and held him in my arms, but he almost instantly expired. I knelt beside him for some minutes, and then made my way to Mr. Turner’s lodge-keeper, his house being the nearest, to ask for assistance. I saw no one near my father when I returned, and I have no idea how he came by his injuries. He was not a popular man, being somewhat cold and forbidding in his manners, but he had, as far as I know, no active enemies. I know nothing further of the matter.’

- `x:boscombe-valley-mystery-0007:claim:1` speaker **James McCarthy** says, about **William Crowder**: He saw William Crowder but was not following his father  
  quote: "he is mistaken in thinking that I was following my father" · pre-check: verbatim in the chunk
- `x:boscombe-valley-mystery-0007:claim:2` speaker **James McCarthy** says, about **James McCarthy**: He left his father and had gone about 150 yards when he heard a hideous outcry  
  quote: "I had not gone more than 150 yards, however, when I heard a hideous outcry behind me" · pre-check: verbatim in the chunk
- `x:boscombe-valley-mystery-0007:claim:3` speaker **James McCarthy** says, about **the deceased**: He saw no one near his father when he returned  
  quote: "I saw no one near my father when I returned" · pre-check: verbatim in the chunk
- `x:boscombe-valley-mystery-0007:claim:4` speaker **James McCarthy** says, about **the deceased**: His father had no active enemies as far as he knows  
  quote: "he had, as far as I know, no active enemies" · pre-check: verbatim in the chunk
- `x:boscombe-valley-mystery-0007:claim:5` speaker **James McCarthy** says, about **the deceased**: His father was of violent temper  
  quote: "my father was a man of a very violent temper" · pre-check: verbatim in the chunk
- `x:boscombe-valley-mystery-0007:relation:1` **James McCarthy** · son of · **the deceased**  
  quote: "Mr. James McCarthy, the only son of the deceased" · pre-check: verbatim in the chunk
- `x:boscombe-valley-mystery-0007:relation:2` **the deceased** · drove to · **Ross**  
  quote: "he had driven over to Ross with John Cobb" · pre-check: verbatim in the chunk
- `x:boscombe-valley-mystery-0007:relation:3` **John Cobb** · groom of · **the deceased**  
  quote: "John Cobb, the groom" · pre-check: verbatim in the chunk
- `x:boscombe-valley-mystery-0007:relation:4` **William Crowder** · game-keeper · **Boscombe Pool**  
  quote: "William Crowder, the game-keeper" · pre-check: verbatim in the chunk
- `x:boscombe-valley-mystery-0007:relation:5` **Hatherley Farm** · home of · **James McCarthy**  
  quote: "returned towards Hatherley Farm" · pre-check: verbatim in the chunk

Check each claim: speaker, content and 'about' are right and supported; each relation: subject,
predicate and object are right. Note missing claims or relations in `fix` of the chunk's first row.

---

## silver-blaze-0004 (`silver-blaze`)

Chunk text:

> “On that evening the horses had been exercised and watered as usual, and the stables were locked up at nine o’clock. Two of the lads walked up to the trainer’s house, where they had supper in the kitchen, while the third, Ned Hunter, remained on guard. At a few minutes after nine the maid, Edith Baxter, carried down to the stables his supper, which consisted of a dish of curried mutton. She took no liquid, as there was a water-tap in the stables, and it was the rule that the lad on duty should drink nothing else. The maid carried a lantern with her, as it was very dark and the path ran across the open moor.
>
> “Edith Baxter was within thirty yards of the stables, when a man appeared out of the darkness and called to her to stop. As he stepped into the circle of yellow light thrown by the lantern she saw that he was a person of gentlemanly bearing, dressed in a grey suit of tweeds, with a cloth cap. He wore gaiters, and carried a heavy stick with a knob to it. She was most impressed, however, by the extreme pallor of his face and by the nervousness of his manner. His age, she thought, would be rather over thirty than under it.
>
> “‘Can you tell me where I am?’ he asked. ‘I had almost made up my mind to sleep on the moor, when I saw the light of your lantern.’
>
> “‘You are close to the King’s Pyland training-stables,’ said she.
>
> “‘Oh, indeed! What a stroke of luck!’ he cried. ‘I understand that a stable-boy sleeps there alone every night. Perhaps that is his supper which you are carrying to him. Now I am sure that you would not be too proud to earn the price of a new dress, would you?’ He took a piece of white paper folded up out of his waistcoat pocket. ‘See that the boy has this to-night, and you shall have the prettiest frock that money can buy.’

- `x:silver-blaze-0004:claim:1` speaker **the stranger** says, about **the stranger**: He had almost decided to sleep on the moor when he saw the lantern  
  quote: "I had almost made up my mind to sleep on the moor" · pre-check: verbatim in the chunk
- `x:silver-blaze-0004:claim:2` speaker **the stranger** says, about **Ned Hunter**: A stable-boy sleeps alone at the stables every night  
  quote: "I understand that a stable-boy sleeps there alone every night" · pre-check: verbatim in the chunk
- `x:silver-blaze-0004:claim:3` speaker **Edith Baxter** says, about **the stranger**: The stranger looked rather over thirty  
  quote: "His age, she thought, would be rather over thirty than under it" · pre-check: verbatim in the chunk
- `x:silver-blaze-0004:relation:1` **Edith Baxter** · maid at · **King’s Pyland**  
  quote: "the maid, Edith Baxter" · pre-check: verbatim in the chunk
- `x:silver-blaze-0004:relation:2` **Edith Baxter** · brought supper to · **Ned Hunter**  
  quote: "carried down to the stables his supper" · pre-check: verbatim in the chunk
- `x:silver-blaze-0004:relation:3` **the stranger** · carried · **heavy stick**  
  quote: "carried a heavy stick with a knob to it" · pre-check: verbatim in the chunk
- `x:silver-blaze-0004:relation:4` **the stranger** · offered paper to · **Edith Baxter**  
  quote: "See that the boy has this to-night" · pre-check: verbatim in the chunk

Check each claim: speaker, content and 'about' are right and supported; each relation: subject,
predicate and object are right. Note missing claims or relations in `fix` of the chunk's first row.

---

## reigate-squires-0009 (`reigate-squires`)

Chunk text:

> “Still at it, then?” said he to Holmes. “I thought you Londoners were never at fault. You don’t seem to be so very quick, after all.”
>
> “Ah, you must give us a little time,” said Holmes good-humoredly.
>
> “You’ll want it,” said young Alec Cunningham. “Why, I don’t see that we have any clue at all.”
>
> “There’s only one,” answered the Inspector. “We thought that if we could only find—Good heavens, Mr. Holmes! What is the matter?”
>
> My poor friend’s face had suddenly assumed the most dreadful expression. His eyes rolled upwards, his features writhed in agony, and with a suppressed groan he dropped on his face upon the ground. Horrified at the suddenness and severity of the attack, we carried him into the kitchen, where he lay back in a large chair, and breathed heavily for some minutes. Finally, with a shamefaced apology for his weakness, he rose once more.
>
> “Watson would tell you that I have only just recovered from a severe illness,” he explained. “I am liable to these sudden nervous attacks.”
>
> “Shall I send you home in my trap?” asked old Cunningham.
>
> “Well, since I am here, there is one point on which I should like to feel sure. We can very easily verify it.”
>
> “What was it?”
>
> “Well, it seems to me that it is just possible that the arrival of this poor fellow William was not before, but after, the entrance of the burglar into the house. You appear to take it for granted that, although the door was forced, the robber never got in.”
>
> “I fancy that is quite obvious,” said Mr. Cunningham, gravely. “Why, my son Alec had not yet gone to bed, and he would certainly have heard any one moving about.”
>
> “Where was he sitting?”
>
> “I was smoking in my dressing-room.”
>
> “Which window is that?”
>
> “The last on the left next my father’s.”
>
> “Both of your lamps were lit, of course?”
>
> “Undoubtedly.”

- `x:reigate-squires-0009:claim:1` speaker **Holmes** says, about **William**: William may have arrived after the burglar entered the house  
  quote: "the arrival of this poor fellow William was not before, but after, the entrance of the burglar into the house" · pre-check: verbatim in the chunk
- `x:reigate-squires-0009:claim:2` speaker **Mr. Cunningham** says, about **the burglar**: The robber never got in  
  quote: "I fancy that is quite obvious" · pre-check: verbatim in the chunk
- `x:reigate-squires-0009:claim:3` speaker **Mr. Cunningham** says, about **Alec Cunningham**: Alec had not gone to bed and would have heard anyone moving about  
  quote: "my son Alec had not yet gone to bed, and he would certainly have heard any one moving about" · pre-check: verbatim in the chunk
- `x:reigate-squires-0009:claim:4` speaker **Alec Cunningham** says, about **Alec Cunningham**: He was smoking in his dressing-room, the last window on the left next his father’s  
  quote: "The last on the left next my father’s" · pre-check: verbatim in the chunk
- `x:reigate-squires-0009:claim:5` speaker **Holmes** says, about **Holmes**: He has only just recovered from a severe illness  
  quote: "I have only just recovered from a severe illness" · pre-check: verbatim in the chunk
- `x:reigate-squires-0009:claim:6` speaker **Alec Cunningham** says, about **the burglar**: The police have no clue  
  quote: "I don’t see that we have any clue at all" · pre-check: verbatim in the chunk
- `x:reigate-squires-0009:relation:1` **Alec Cunningham** · son of · **Mr. Cunningham**  
  quote: "my son Alec" · pre-check: verbatim in the chunk
- `x:reigate-squires-0009:relation:2` **Alec Cunningham** · occupied · **dressing-room**  
  quote: "I was smoking in my dressing-room" · pre-check: verbatim in the chunk
- `x:reigate-squires-0009:relation:3` **Holmes** · friend of · **Watson**  
  quote: "My poor friend’s face" · pre-check: verbatim in the chunk

Check each claim: speaker, content and 'about' are right and supported; each relation: subject,
predicate and object are right. Note missing claims or relations in `fix` of the chunk's first row.

---

## naval-treaty-0007 (`naval-treaty`)

Chunk text:

> “I did exactly what he indicated, and waited until the other clerks had departed. One of them in my room, Charles Gorot, had some arrears of work to make up, so I left him there and went out to dine. When I returned he was gone. I was anxious to hurry my work, for I knew that Joseph—the Mr. Harrison whom you saw just now—was in town, and that he would travel down to Woking by the eleven o’clock train, and I wanted if possible to catch it.
>
> “When I came to examine the treaty I saw at once that it was of such importance that my uncle had been guilty of no exaggeration in what he had said. Without going into details, I may say that it defined the position of Great Britain towards the Triple Alliance, and fore-shadowed the policy which this country would pursue in the event of the French fleet gaining a complete ascendancy over that of Italy in the Mediterranean. The questions treated in it were purely naval. At the end were the signatures of the high dignitaries who had signed it. I glanced my eyes over it, and then settled down to my task of copying.
>
> “It was a long document, written in the French language, and containing twenty-six separate articles. I copied as quickly as I could, but at nine o’clock I had only done nine articles, and it seemed hopeless for me to attempt to catch my train. I was feeling drowsy and stupid, partly from my dinner and also from the effects of a long day’s work. A cup of coffee would clear my brain. A commissionnaire remains all night in a little lodge at the foot of the stairs, and is in the habit of making coffee at his spirit-lamp for any of the officials who may be working over time. I rang the bell, therefore, to summon him.

- `x:naval-treaty-0007:claim:1` speaker **the narrator** says, about **the naval treaty**: The treaty defined Britain’s position towards the Triple Alliance  
  quote: "it defined the position of Great Britain towards the Triple Alliance" · pre-check: verbatim in the chunk
- `x:naval-treaty-0007:claim:2` speaker **the narrator** says, about **the narrator**: He could not catch his train because he was too slow  
  quote: "it seemed hopeless for me to attempt to catch my train" · pre-check: verbatim in the chunk
- `x:naval-treaty-0007:claim:3` speaker **the narrator** says, about **the naval treaty**: The treaty was in French with twenty-six articles  
  quote: "written in the French language, and containing twenty-six separate articles" · pre-check: verbatim in the chunk
- `x:naval-treaty-0007:relation:1` **the narrator** · nephew of · **the uncle**  
  quote: "my uncle had been guilty of no exaggeration" · pre-check: verbatim in the chunk
- `x:naval-treaty-0007:relation:2` **the commissionnaire** · makes coffee for · **the narrator**  
  quote: "is in the habit of making coffee at his spirit-lamp for any of the officials" · pre-check: verbatim in the chunk
- `x:naval-treaty-0007:relation:3` **the narrator** · copying · **the naval treaty**  
  quote: "settled down to my task of copying" · pre-check: verbatim in the chunk

Check each claim: speaker, content and 'about' are right and supported; each relation: subject,
predicate and object are right. Note missing claims or relations in `fix` of the chunk's first row.

---
