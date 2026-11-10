# Nov 10th 2026
- Fixed crash on analyse. It was because of problems with the memory mapping, it was touching things it shouldn't
- Fixed text spilling into the wrong places, such as the "Can't" from "Can't talk right now..." getting into "Flatter" and becoming "FlattCan't". Also because of problems with the memory mapping.
- Fixed missing sprites for Mark in the black Mark patch. Including his full body one at the ending.

# Nov 9th 2026
- There are less MTL lines now. The ones that remain are basically only very short that are basically impossible to translate as anything else.
- Fixed two sets of choices to fit properly on screen. One of them was a very important one.
- Fixed some line breaks in areas where they aren't allowed.
- Fixed repeated demon negotiation choices because the game rejected their addresses.
- Fixed potential issues I'm too dumb to explain.
- Fixed truncated Persona names during negotiation.
- Fixed truncated demon names in the screen you get when you have to replace a demon's card. Also made it VWF.
- Item acquire text is now VWF.
- Fixed "You have \[Number\] coins." and similar texts, they previously said "\[Number\]" because of bad porting practices.

# Nov 7th 2026
- Fixed multiple misplaced translation lines. I'm so sorry I let that slip.
- Extended the limit of the name and surname of the player to 8 characters each.
- Fixed the L1 L2 R1 R2 screens in the battle. They're now translated and VWF.
- Fixed the Persona status screens showing the incorrect Persona names in some situations.
- Fixed multiple different Persona status screens that were not using VWF.
- Fixed a Persona status screen that was showing one line of gibberish for everything.
- Added QOL patches: running in dungeons, allow skipping FMVs,
and up as upper right movement in the isometric areas (like the PSP version had as an option).
- Split the Double rewards and Halve encounters into two separate things.
- Fixed some texts not being injected because they were too long.
- Fixed some texts being cut off because they were too long.
- Fixed commas not being allowed in the smallfont in some contexts.
- Fixed stupid typo ConvinienceStore -> C-Store in the map.
I meant to have it as ConvenienceStore because the space caused the text to be too long for the map text renderer
and I failed to fix that, but I mistyped it and didn't notice. The e made it too long still tho so C-store it is.
- Split the Mikage Police Station string so it can be called that in the overworld, but in the map subtitle it's just Police Station.
Similar to how the game already did with Mikage Hospital.
