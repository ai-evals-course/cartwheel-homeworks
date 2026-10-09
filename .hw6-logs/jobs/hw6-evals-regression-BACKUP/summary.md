## Cartwheel evaluation results

| Case | Kind | Passed | Trials | pass@1 | pass@3 | pass@5 | pass^5 | CI decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `e-007` | regression | 0 | 5 | 0.000 | 0.000 | 0.000 | 0.000 | block |
| `e-009` | capability | 3 | 5 | 0.600 | 1.000 | 1.000 | 0.000 | pass |
| `e-010` | regression | 4 | 5 | 0.800 | 1.000 | 1.000 | 0.000 | block |

Infrastructure problems:
- e-009: 1 trial(s) did not produce a reward

Regression cases block on any failed trial. Capability cases do not block.
