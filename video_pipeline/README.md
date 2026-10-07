# Brix video workflow

The current template produces 1080 × 1350 (4:5), 30 fps ads. Each ad has two music variants with identical visuals: **A — Original Brix music** and **B — Curiosity** by Diego Nava. Both retain the 20% music amplitude reduction (`gain: 0.8`); narration is normalized separately.

## Current jobs and exports

`batches/meta_4x5.json` lists the 12 ads. Jobs are grouped by ad:

```text
video_pipeline/jobs/roof_1/
  A_original.json
  B_curiosity.json

output/roof_1/
  output/
    BRIX_Roofing_01_LocalCalls_4x5_A_Original.mp4
    BRIX_Roofing_01_LocalCalls_4x5_B_Curiosity.mp4
  captions/          matching SRT files
  storyboard/        prepared and finished frame sheets
  project/
    A_original/      timeline, graphics, review frames, logs, quality report
    B_curiosity/     mix settings, quality report, identical-video verification
```

There is one top-level folder per ad and exactly two finished MP4s in each `output/`. The niche, script number, aspect ratio, test arm, and music name are explicit in the filename. Use these names to identify the pair when uploading for an A/B music test. No ad is published by this workflow.

`output/all_outputs/` additionally contains flat copies of all 24 finished MP4s, retaining their A/B filenames for easy bulk selection. The per-ad originals stay in place. Maintain and verify this collection in both output locations whenever delivering updated ads.

The September 28 cleanup replaces the earlier policy of retaining historical exports: once the new pair is validated, remove superseded generated versions and redundant comparison folders. Keep inputs, licenses, scripts, catalogs, and reviewed timings. Mirror the final structure to `C:\Users\adani\Videos\Brix Ads\output` and verify copies. The workspace `output/` is canonical.

## Render and review

Run these commands from the workspace in WSL/bash:

```bash
# Review actual footage crops, captions, and every numbered service reveal
./video.sh prepare video_pipeline/jobs/roof_1/A_original.json --storyboard

# Render A; create B by copying its video and rebuilding only the music mix
./video.sh pair video_pipeline/jobs/roof_1/A_original.json video_pipeline/jobs/roof_1/B_curiosity.json

# A smaller 576 × 720 draft, isolated under the ad's preview/ directory
./video.sh render video_pipeline/jobs/roof_1/A_original.json --preview

./video.sh doctor
./video.sh test
```

`pair` refuses to replace an existing B export accidentally. For an intentional replacement, finish the revised configuration and review its prepared storyboard, then remove the superseded pair and run the command. For a new creative, create another ad ID and folder.

To render all current ad pairs:

```bash
for first in video_pipeline/jobs/*/A_original.json; do
  ./video.sh pair "$first" "${first%/*}/B_curiosity.json" || break
done
```

The `render`, `batch`, and `remix` commands also remain available independently. `remix <B-job> --source-job <A-job>` validates that only music and file identity differ, copies the approved video without re-encoding, and verifies identical video packet hashes. It rejects changed visuals, narration, brand settings, captions, or shot timing. Renders keep partial files in `project/` until all technical checks pass.

## Shared design

`brands/brix/brand.json` controls fonts, colors, logo, dimensions, and layout. The centered top banner shows the supplied logo, niche label, and “RANK #1 ON GOOGLE LOCALY”, with #1 in orange. Keep the requested spelling. Captions are centered at x=540 and y=1120 on the 1080 × 1350 canvas. Header, card, and closing text have been reflowed for 4:5; original footage is cropped to 4:5 around each shot's saved subject center.

The opening price/intro bubble is removed. Before the first service, footage and captions carry the opening under the brand banner. In each job, `creative.offer.start` equals the first benefit's `start`, and there is no `intro` or `hook` text.

The service card uses blurred live footage with a navy tint, white type, and a white outline. Each numbered row appears at its spoken phrase and remains until the card ends. Plumbing currently lists three services; roofing and septic list four. The card's height follows the row count. `layout.offer_card` controls bounds, blur, tint, text offsets, type sizes, and spacing. Prepared storyboards include every reveal. Resolved times and geometry are recorded in `project/<mix>/offer_layout.json`.

The closing CTA is white text over footage (“Get found. Get more calls.” and “Tap to learn more”), with a gently moving orange downward chevron. Its layout is under `layout.cta`. The later reassurance panel and full supplied voiceover remain. There is no opening intro panel or simulated CTA button.

## New ad

1. Put the recording, script, and footage in their category folders under `voiceover/`, `transcripts/`, and `stock_footage/`.
2. Use `./video.sh new <ad-id> --niche '<audience>' --audio <file> --transcript <file> --job video_pipeline/jobs/<ad-id>/A_original.json --music original`. The footage catalog defaults to the recording's category; use `--catalog` when needed.
3. Set the A output filename using the convention above and `artifact_version: "A_original"`. Configure creative copy and phrase anchors. Pin curated shots after review.
4. Clone A as `B_curiosity.json`, changing only ID/output, `artifact_version: "B_curiosity"`, and music. Use the `relaxed_groove` entry from `music/catalogs/approved.json` for B.
5. Prepare a storyboard, inspect the framing and copy, then run `pair`. Add the pair to the batch manifest if it belongs in the current delivery set.

`new` creates the top banner and closing CTA, with no assumed price or service offer. `--niche` is required and supports labels such as roofers, plumbers, or septic contractors; longer text is fitted to the banner and rejected if unreadable. An optional `--hook` is available for other briefs, but current ads intentionally omit opening hook panels.

## Timing and captions

Each graphic and shot cut can use a transcript phrase instead of fixed seconds:

```json
{"start": {"phrase": "we build"}, "end": {"phrase": "No ad spend", "offset": -0.1}}
```

Use `edge: "end"` for the phrase's end; repeated phrases require a zero-based `occurrence`. Ambiguous/missing anchors are rejected. Plain seconds and `{"end_offset": -5.8}` also work. Numbered service starts must be ordered and fall inside the card interval.

Reviewed word timing files are in `alignments/<ad>.words.json`; transcript correction notes are in `alignments/<ad>.review.json` where applicable. Imported timing data is bound to the recording contents, so moving inputs is supported but changing a recording requires realignment. Captions keep the supplied wording, group into at most two lines, fit the safe width, and highlight the spoken word. Numeric substitutions can display “two hundred ninety-seven dollars” as `$297` while retaining the whole spoken span.

Without imported timings, speech recognition runs locally and compares the recording with the transcript. Inspect `alignment_report.json` if alignment is uncertain; do not claim precision from estimated timings. The first run installs pinned packages and downloads the speech model as needed. Dependencies, raw shot encodes, and media probes are cached under `~/.cache/brix-video` (override with `BRIX_VIDEO_CACHE`).

## Music and checks

The approved music catalog retains the original synthesized bed and Curiosity; source metadata and licenses are under `music/tracks/` and `music/licenses/`. Gain is applied after music normalization. The default for standalone new ads remains Curiosity; A/B pairs explicitly specify both tracks.

`audition <job> --catalog <catalog> --duration 12` can produce temporary music comparisons under the ad's `preview/` folder, preserving the finished video's aspect ratio. Remove obsolete audition folders when organizing the delivery.

Validation covers exact dimensions, frame count, full video/audio decode, duration, black intervals, loudness, peak headroom, caption width, crop bounds, shot continuity, service-row timing, and source overrun. A/B remixes additionally verify unchanged compressed video frames. Review actual images as well: automation does not judge subjects or the correctness of the ad's spoken claims.
