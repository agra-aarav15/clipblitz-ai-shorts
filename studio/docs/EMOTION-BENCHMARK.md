# Emotion benchmark

This is the check that came out of a concrete bad rating: a suspense scene with an
acoustic sting was being scored as a comedy because the old `laughter` feature treated
any energy burst above the video baseline as a laugh. The engine now separates the two:

- `reaction` is the measured acoustic burst. It can raise energy, but it is not a joke.
- `laughter` and `tail_laugh` are only set when the transcript has comedy evidence.
- The judge returns a required `emotion_label` from one taxonomy.
- If the judge calls a suspense transcript funny, the transcript's suspense evidence wins
  and the cut is flagged `emotion_mismatch` instead of silently becoming comedy.

## Taxonomy

`funny`, `suspense`, `shock`, `emotional`, `inspiring`, `angry`, `wholesome`,
`hype`, `informative`, `awkward`.

Every selected clip carries its dominant label; the card shows it next to the tier.
English, Hinglish, Devanagari Hindi and Urdu cues are included because the first Raj
Shamani test exposed that an English-only taxonomy scored a Hindi transcript as empty.

## Runs

All runs used ARGON, `top_n=3`, and the same local build. The judge was rate-limited
during these runs, so the clips are honestly `unverified`; the labels are the measured
transcript labels, not a judge claim.

| Source | Job | Clips | Emotion labels | Scores | What it proves |
|---|---|---:|---|---|---|
| F1 team radio, funny compilation | `8549c5ea` | 3 rendered, final judge rejected all | funny/awkward candidates | - | Fast-cut compilation; the final judge refuses to call these self-contained. |
| Alfred Hitchcock, suspense episode | `b675e364` | 2 | suspense, suspense | 78, 76 | One verified by the local judge; no laugh label on a tense scene. |
| Raj Shamani, habits interview | `896363e3` | 3 | suspense, suspense, inspiring | 82, 77, 80 | One verified by the local judge; a different emotion from the same channel. |
| Raj Shamani, undercover story | `d7c513de` | 1 | suspense | 79 | A suspense interview gets a suspense card, not a laugh card. |

The first Hindi-only Raj clip (`0bf9c035`) exposed a real gap: the English cue table
returned `informative` with an all-zero emotion map. Hindi/Urdu cues were added and the
unit suite now covers all ten labels.

## Reproduce

```bash
python scripts/test_emotion.py
python scripts/test_argon.py
```

The unit suite is offline and deterministic; it does not call a provider. The four
runs above are local media runs and are not part of CI.
