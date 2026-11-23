# Human preference results

Study `rides-340deafa42`. Primary analysis: 24 different pairs, each rated by two people. W/L/T/? = full harness preferred / comparator preferred / tie / unable to judge. Each contrast compares two registered endpoints from one initial draw. Hidden repeats are excluded from preference counts.

| Contrast | Model | Reviewer 1 (W/L/T/?) | Reviewer 2 | Pooled votes |
|---|---|---|---|---|
| AD | deepseek-v4.1-flash-1017 | 4/0/0/0 | 4/0/0/0 | 8/0/0/0 |
| AD | qwen3.8-flash | 0/0/0/4 | 3/0/1/0 | 3/0/1/4 |
| AD | qwen4-max | 2/1/1/0 | 2/1/1/0 | 4/2/2/0 |
| AD | All | 6/1/1/4 | 9/1/2/0 | 15/2/3/4 |
| CD | deepseek-v4.1-flash-1017 | 2/1/1/0 | 3/0/1/0 | 5/1/2/0 |
| CD | qwen3.8-flash | 1/0/2/1 | 4/0/0/0 | 5/0/2/1 |
| CD | qwen4-max | 2/1/1/0 | 2/2/0/0 | 4/3/1/0 |
| CD | All | 5/2/4/1 | 9/2/1/0 | 14/4/5/1 |

Exact four-category agreement: 13/24 (54.2%); unweighted Cohen’s κ = 0.254.

| Original | Swapped | Reviewer 1 (orig/swap) | Reviewer 2 (orig/swap) |
|---|---|---|---|
| P06 | P02 | W/W | W/W |
| P19 | P08 | W/W | W/W |
| P04 | P09 | W/W | W/W |

Reviewer 1 self-consistency: 3/3.  
Reviewer 2 self-consistency: 3/3.  

## Both reviewers explicitly preferred D

| Pair | Model | Initial draw | Contrast |
|---|---|---|---|
| P03 | deepseek-v4.1-flash-1017 | ostrich-bicycle-02 | AD |
| P04 | qwen4-max | toucan-tricycle-01 | CD |
| P06 | qwen3.8-flash | toucan-tricycle-02 | CD |
| P07 | deepseek-v4.1-flash-1017 | ostrich-tricycle-01 | CD |
| P10 | deepseek-v4.1-flash-1017 | toucan-bicycle-03 | AD |
| P13 | deepseek-v4.1-flash-1017 | ostrich-tricycle-03 | AD |
| P18 | deepseek-v4.1-flash-1017 | toucan-tricycle-01 | AD |
| P19 | deepseek-v4.1-flash-1017 | ostrich-bicycle-03 | CD |
| P21 | qwen4-max | ostrich-tricycle-03 | AD |
| P24 | qwen4-max | toucan-bicycle-02 | CD |
| P25 | qwen4-max | toucan-bicycle-03 | AD |

Preferences are descriptive for the selected pairs. A working scene preferred to a blank start is not by itself evidence of more natural pedaling. See human-decoded.csv for all votes including repeated pairs.
