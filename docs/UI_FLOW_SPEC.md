# MovAI UI Flow Specification

## Screen 1: Projects

Displays project cards with:

- Project name
- Description
- Series count
- Last updated time

Actions:

- Create project
- Open project
- Edit project

## Screen 2: Series

Displays series cards inside the selected project.

Each card shows:

- Series title
- Genre
- Season count
- Episode count
- Story processing status

Actions:

- Create series
- Open series

## Screen 3: Series workspace

Contains:

- Story source panel
- Processing progress
- Duration estimate
- Season list
- Character/continuity area
- Master-script status

## Story submission states

```text
Not started
Uploaded
Validating
Parsing
Chunking
Embedding
Ready for analysis
Analyzing
Review required
Complete
Failed
```

## User restrictions

- First season is created through planning after story processing.
- Episodes cannot be manually added.
- Characters originate from story analysis.
- Character versions/assets may be reviewed after extraction.

## Future review screens

- Complexity summary
- Extracted characters
- Timeline/events
- Continuity conflicts
- Master script
- Season plan
- Episode plan
