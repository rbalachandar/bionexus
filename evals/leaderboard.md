# BioNexus eval leaderboard

Run 2026-09-09 20:40 · mean **0.893** · all pass

### epistemics — mean 0.944

| task | score | pass | time | notes |
|---|---|---|---|---|
| hit-recovery | 0.833 | ✅ | 6.5s | 1.0 confident-correct · 0.5 honest abstain · 0 wrong |
| verdict-honesty | 1.000 | ✅ | 8.2s | bar at E-03's true IC50 (10.75 uM); 4 borderline CIs, 0 overconfident verdicts |
| confirmation-coverage | 1.000 | ✅ | 4.8s | no confirmations at all -> 0 (mechanism unused) |

### models — mean 0.842

| task | score | pass | time | notes |
|---|---|---|---|---|
| model-lipophilicity | 1.000 | ✅ | 9.1s | char3gram-ridge spearman=0.502 (floor 0.034, bar 0.3) |
| model-esol | 1.000 | ✅ | 2.6s | char3gram-ridge spearman=0.706 (floor -0.110, bar 0.5) |
| model-hiv | 0.526 | ✅ | 12.7s | char3gram-ridge roc_auc=0.761 (floor 0.500, bar 0.65) |
