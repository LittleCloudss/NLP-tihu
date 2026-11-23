# Visual judge calibration

Qwen4-Max evaluated only anonymous rendered pixels. One model call examined each complete phase grid. Paired decisions were independently repeated after exchanging A and B. On each locked set, the primary gate requires at least 11/12 core pairs to prefer the unaltered scene in both orders, at least 2/3 for each fault, and at least 5/6 correct single-clip diagnoses for each core fault. A tie, positional disagreement, unobservable verdict, or invalid reply cannot establish a correct directional preference.

| Set | Base scenes | Core pairs correct in both orders | All eight fault types, both orders |
|---|---:|---:|---:|
| Development (approved draft 2) | 1 | 1/4 | 3/8 |
| Initial locked set (includes approved draft 6) | 3 | 2/12 | 10/24 |
| Independent reserve, one prompt refinement | 3 | 3/12 | 13/24 |

## Diagnoses by fault

| Set | Condition | Stable correct preference | Targeted single-clip verdict |
|---|---|---:|---:|
| development | feet_raised | 0/1 | 0/2 |
| development | crank_stopped | 1/1 | 0/2 |
| development | crank_reversed | 0/1 | 0/2 |
| development | wheel_reversed | 0/1 | 0/2 |
| development | joint_gap | 1/1 | 0/2 |
| development | penetration | 0/1 | 0/2 |
| development | wrong_bird | 1/1 | 0/2 |
| development | wrong_vehicle | 0/1 | 0/2 |
| development | self | 0/1 | — |
| first | feet_raised | 1/3 | 0/6 |
| first | crank_stopped | 1/3 | 3/6 |
| first | crank_reversed | 0/3 | 0/6 |
| first | wheel_reversed | 0/3 | 0/6 |
| first | joint_gap | 3/3 | 3/6 |
| first | penetration | 1/3 | 0/6 |
| first | wrong_bird | 3/3 | 0/6 |
| first | wrong_vehicle | 1/3 | 2/6 |
| first | self | 0/3 | — |
| reserve | feet_raised | 2/3 | 0/6 |
| reserve | crank_stopped | 1/3 | 3/6 |
| reserve | crank_reversed | 0/3 | 0/6 |
| reserve | wheel_reversed | 0/3 | 0/6 |
| reserve | joint_gap | 3/3 | 2/6 |
| reserve | penetration | 2/3 | 0/6 |
| reserve | wrong_bird | 3/3 | 0/6 |
| reserve | wrong_vehicle | 2/3 | 2/6 |
| reserve | self | 0/3 | — |

## Visibility and ties

- development. On the unobstructed positive controls, yes counts were {'crank_forward': 2, 'wheel_forward': 2, 'left_contact': 2, 'right_contact': 2, 'connected': 2, 'clear_of_penetration': 2}. On the occluded controls, unobservable counts were {'crank_forward': 2, 'wheel_forward': 2, 'left_contact': 2, 'right_contact': 2, 'connected': 2, 'clear_of_penetration': 2}. Each denominator is 2.
- first. On the unobstructed positive controls, yes counts were {'crank_forward': 6, 'wheel_forward': 6, 'left_contact': 6, 'right_contact': 6, 'connected': 6, 'clear_of_penetration': 6}. On the occluded controls, unobservable counts were {'crank_forward': 6, 'wheel_forward': 6, 'left_contact': 6, 'right_contact': 6, 'connected': 3, 'clear_of_penetration': 5}. Each denominator is 6.
- reserve. On the unobstructed positive controls, yes counts were {'crank_forward': 6, 'wheel_forward': 6, 'left_contact': 6, 'right_contact': 6, 'connected': 6, 'clear_of_penetration': 6}. On the occluded controls, unobservable counts were {'crank_forward': 4, 'wheel_forward': 6, 'left_contact': 4, 'right_contact': 4, 'connected': 4, 'clear_of_penetration': 5}. Each denominator is 6.

The gate remained closed after the single permitted prompt revision. No formal generation, arm evaluation or cross-model success rate was produced.

The first and reserve cohorts contain different original rides. Their percentages measure each prompt on its own locked set; a between-cohort difference cannot isolate a prompt effect. The two shifted phase grids of one clip and the side swaps of one pair are repeated observations, not independent rides.

The controls cover four mechanical faults and four appearance faults. The left and right contacts must both be diagnosed as unsupported on the two-foot lift. Foot displacement and the signed angle traveled by the crank and front marker were independently recorded across 96 times; labels and numerical traces were withheld from the judge. The two human-approved pelican references are visual anchors and have separate mechanical observations.

The tricycle heading uses the midpoint of the rear axle. The former single rear reference could produce a false direction error. All three configured endpoints accepted a 32,000-token output ceiling. Neither transfer species has a sculpting preset; flamingo on a bicycle had appeared in an earlier benchmark.

[Calibration protocol](../../artifacts/final-study/protocol/calibration.json) · [Model output ceilings](../../artifacts/final-study/protocol/limits.json) · [Gate decision](../../artifacts/final-study/protocol/gate.json) · [Judgments and orders](calibration-judgments.csv).
