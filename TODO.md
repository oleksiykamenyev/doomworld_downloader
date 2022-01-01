# Uploader TODO.md

## TODO

### Features

- [ ] Detect Compet-N textfiles  
- [ ] Create idgames/DSDA WAD checksum validation tool  
- [ ] Create DSDA demo/zip updater automation  
- [ ] Process raw data for multi-level wads  
- [ ] Manage alternative command lines more cleanly
  - Specifically: we need the script to be smart enough to not create false positives for synced demos (e.g., running with thissuxx map 1 might seem like a sync)  
- [ ] Handle Hexen movies  
- [ ] LMP Python library  
- [ ] Fuzzy handling of JSON key certainty for uploader  
- [ ] Handle theoretical E1M10, etc. episodic numbering  

### Infrastructure
- [ ] Better name for tool (DSDA uploader?)  
- [ ] Sorting tool for thread YAML  
- [ ] Sorting tool for WAD YAML  
- [ ] Custom exceptions for DSDA uploader  
- [ ] Create parser base class  
- [ ] Doomworld data retriever should be a class  
- [ ] Unit tests  
- [ ] Clean up noisy logging from underlying libraries  
- [ ] Use pkg_resources for config files  

## In Progress

## Blocked on DSDA-Doom changes

- [ ] DSDA-Doom should return accurate analysis/levelstat info for Hexen and Heretic  
- [ ] Handle UV-Max secret/kill exceptions  
- [ ] Handle maps with no exits  
- [ ] Remove override of UV Tyson to Tyson category name  
