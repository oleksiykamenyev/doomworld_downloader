# DSDA Admin Client Concept

### Motivation
There likely isn't someone in the community that has the dedication required to single-handedly maintain the archive, year after year, with all the manual labor required, like Andy (and in the past, Opulent) have. Furthermore, this burden *shouldn't* be put on any one person. To this end, we should have a team of administrators in charge of archive maintenance, and we should make the process of maintaining the archive as simple and convenient as possible.

### Why Admins?
An alternative would be to allow users to submit runs directly, but this has a lot of possible issues, so I don't think it's worth pursuing (at this time). These issues include people not knowing how to label their runs and / or putting in the wrong data. This can happen with admins as well, but to a lesser extent. Additionally, there is no way to convince everyone to stop doing things the way they have done for years, to either skip the forum (which would be bad for discussion / community) or do the work of uploading a post *and* going to dsda and submitting directly.

### Basic Requirements
The client is cross-platform (windows / linux / mac), so that anyone can use it. It has a real user interface (not command-line driven). It connects directly with the dsda api, uploading demos and wads, handling errors gracefully. It provides a smooth user experience and, in general, makes things as low-effort as possible for the user. It allows manual entry of all data, but supports automated collection of as much information as possible. This includes not only filling in missing data, but also verifying or corroborating existing data. It can toggle different environments of the api (local vs production).

### Demo Flow

#### Step 1: Forum Post
A demo is posted to the forums. Generally the following information is immediately available:

- Player name(s)
- Wad
- Level
- Category
- Time (with or without tics)
- Tas or not
- Coop or not
- Zip file

#### Step 2: Open Client
The client must have some things manually:

- Player name(s)
- Wad
- Category
- Tas or not
- Zip file

It can determine the following for demos that play back in prboom+:

- Time (including tics, from levelstat)
- Coop or not (from the demo header)
- Level (from levelstat or from demo header)
- Kills / items / secrets
- Recording date

Other things may be in the forum post or in the text file:

- Engine
- Recording date (more reliable)
- Notes (e.g., "Also reality" or "Intended route")
- Video link

For demos that need a different port, those values must be supplied by the user. In this case, step 4 and 5 are skipped.

The user opens the client and inputs the manually required fields.

#### Step 3: Resolve Wad
With the wad and zip file specified, the client should find the wad. It checks a local cache of wad files to see if it already has it. If not, it checks dsda3 for the wad. If the wad isn't there, the client prompts the user for help. They can click a "fetch from idgames" option that tries to find the wad on idgames, or they can select a file location if they have it downloaded somewhere. If it isn't on idgames, the user will fill out a new form and upload it. Note that some wads are commercial and can't be uploaded to dsda, so they will not be found but also shouldn't be uploaded. For this reason there should be an option like "store in cache and skip upload".

#### Step 4: Resolve lmp
With the wad ready, the client must unzip the file and see how many lmp files are there. If there is more than one, the client should prompt the user to pick one. Generally, it will be easy to tell which one should be selected without looking into anything. Example: `ab01-123.lmp` and `ab01-bonus.lmp`. This information is also typically in the forum post or the text file.

#### Step 5: Run Analysis
The client should play back the demo (which is pretty fast when prboom+ is in nonrender mode), giving the user some kind of "loading" type icon while it's processing. This will then fill in the information mentioned above, that can be collected from the lmp automatically. The demo might desync here, in which case the user should be prompted - maybe the wad is wrong? If they cannot get it to work, then they probably need to ask what's going on on the forum - that's not a task for the client.

#### Step 6: Verify
The user should look at the information that the client renders as a form. Some of it was added by the user and some by the client itself - fields should have a different highlight / color / etc indicating manual, automatic, or missing information. There should be a button the user can click that opens the text file(s), either inside the client or outside. Then they can check for the engine if it is missing, they can see if the recording date is indicated in the text file (so they can check against the automated value), and they can look for anything else relevant.

#### Step 7: Submit
If everything looks good, the user clicks a button that posts the data to the API. If an error comes back, they should be shown to the user and we return to Step 6. **The client must remember some information from the response**. This includes the demo id and the file id. Those would be necessary for demo packs (see below) and for making a correction if the user realizes they made some error.

### Demo Pack Flow
To Do

### General Info

- For the most part, where it makes sense, every part of the interface should be responsive at all times. While the analysis is running, I should be able to click a button to open the text file, and fill in the engine, for example. Another example: after realizing you just started an analysis with the wrong wad, you can cancel the analysis early. An exception would be the submit button, which shouldn't be clickable unless all required fields are filled in.
- Fields should be validated when possible. Example: the recording date should be after 1994.
- Text file analysis should be as advanced as possible. Example: scan the file for the names of source ports, and prefill the one detected, if only one was found. Example: look for various date formats, and put a warning on the recording date if they don't match.
- There should be a selector somewhere to see the history of uploads, with ids and file ids, which may be needed for any number of things.
