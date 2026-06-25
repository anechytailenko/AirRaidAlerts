
# Interactice analysis demo

![Demo of the application](demo/record_01.gif)

# Train process 
![](/demo/train_01.png)

![](/demo/train_02.png)

All training and validation plots can be found here : https://wandb.ai/anna-nechytailenko-kyiv-school-of-economics/airraid-stgnn/workspace?nw=nwuserannanechytailenko

# Test metrics

**Active oblasts in aggregate: 24** (excluded 3 with zero alerts in the 2026 test window: Crimea, Luhansk, Sevastopol). Excluded oblasts are still plotted as *No Data Available* below.

Global mean over the 24 active oblasts × 6 horizons — **PR-AUC 0.336**, **F1-macro 0.472**, **ROC-AUC 0.608**.

### Global metrics by horizon (k = 1..6, active oblasts only)

| Horizon | PR-AUC | F1-macro | ROC-AUC |
| --- | --- | --- | --- |
| k1 | 0.440 | 0.578 | 0.708 |
| k2 | 0.321 | 0.483 | 0.605 |
| k3 | 0.316 | 0.457 | 0.592 |
| k4 | 0.316 | 0.442 | 0.587 |
| k5 | 0.316 | 0.437 | 0.582 |
| k6 | 0.307 | 0.434 | 0.575 |
| **mean** | 0.336 | 0.472 | 0.608 |

### Per-oblast summary (averaged over horizons)

| Oblast | id | PR-AUC (mean) | F1-macro (mean) | ROC-AUC (mean) | alert rate |
| --- | --- | --- | --- | --- | --- |
| Kharkiv | 8 | 0.698 | 0.410 | 0.579 | 0.648 |
| Dnipropetrovsk | 5 | 0.593 | 0.375 | 0.535 | 0.571 |
| Sumy | 21 | 0.568 | 0.408 | 0.540 | 0.540 |
| Chernihiv | 2 | 0.540 | 0.475 | 0.565 | 0.495 |
| Zaporizhzhia | 26 | 0.469 | 0.321 | 0.524 | 0.448 |
| Chernivtsi | 3 | 0.426 | 0.588 | 0.817 | 0.075 |
| Kherson | 9 | 0.403 | 0.513 | 0.567 | 0.363 |
| Mykolaiv | 16 | 0.390 | 0.443 | 0.575 | 0.340 |
| Poltava | 18 | 0.384 | 0.313 | 0.557 | 0.342 |
| Volyn | 24 | 0.342 | 0.453 | 0.582 | 0.282 |
| Khmelnytskyi | 10 | 0.342 | 0.674 | 0.770 | 0.072 |
| Ternopil | 22 | 0.325 | 0.584 | 0.799 | 0.058 |
| Donetsk | 6 | 0.318 | 0.257 | 0.456 | 0.337 |
| Zakarpattia | 25 | 0.316 | 0.520 | 0.811 | 0.054 |
| Odesa | 17 | 0.303 | 0.535 | 0.561 | 0.259 |
| Kyiv | 12 | 0.274 | 0.474 | 0.574 | 0.216 |
| Kirovohrad | 11 | 0.252 | 0.324 | 0.558 | 0.211 |
| Cherkasy | 1 | 0.226 | 0.467 | 0.565 | 0.173 |
| Lviv | 15 | 0.217 | 0.513 | 0.616 | 0.140 |
| Zhytomyr | 27 | 0.208 | 0.559 | 0.629 | 0.119 |
| Kyiv City | 13 | 0.156 | 0.531 | 0.567 | 0.114 |
| Rivne | 19 | 0.135 | 0.543 | 0.644 | 0.063 |
| Vinnytsia | 23 | 0.115 | 0.528 | 0.578 | 0.065 |
| Ivano-Frankivsk | 7 | 0.074 | 0.520 | 0.626 | 0.026 |
| Crimea *(no data)* | 4 | — | — | — | 0.000 |
| Luhansk *(no data)* | 14 | — | — | — | 0.000 |
| Sevastopol *(no data)* | 20 | — | — | — | 0.000 |


# A3T-GCN Holdout Evaluation: June 1 – June 24, 2026

**Evaluation Period:** June 1, 2026 — June 24, 2026  
**Scope:** 27 Oblasts / Regions (including Kyiv City, Crimea, and Sevastopol)  

This document contains the test run results for the A3T-GCN model across all Ukrainian oblasts. Each plot displays a 2x3 grid evaluating the 6 forecast horizons ($k=1$ to $6$). 

The visualizations below display the **predicted P(alert)** (navy line) versus the **actual active alerts** (crimson shading), along with the **decision threshold** applied for that specific horizon (dashed gray line).

---

## Evaluation Metrics Summary
*Detailed metrics are saved in `plots/per_oblast/metrics_per_oblast_horizon.csv` and summarized in `plots/per_oblast/metrics_summary.md`.*

---

## Per-Oblast Visualizations

### Cherkasy
![](plots/per_oblast/horizon_eval_cherkasy.png)

### Chernihiv
![](plots/per_oblast/horizon_eval_chernihiv.png)

### Chernivtsi
![](plots/per_oblast/horizon_eval_chernivtsi.png)

### Crimea - no data
![](plots/per_oblast/horizon_eval_crimea.png)

### Dnipropetrovsk
![](plots/per_oblast/horizon_eval_dnipropetrovsk.png)

### Donetsk
![](plots/per_oblast/horizon_eval_donetsk.png)

### Ivano-Frankivsk
![](plots/per_oblast/horizon_eval_ivano_frankivsk.png)

### Kharkiv
![](plots/per_oblast/horizon_eval_kharkiv.png)

### Kherson
![](plots/per_oblast/horizon_eval_kherson.png)

### Khmelnytskyi
![](plots/per_oblast/horizon_eval_khmelnytskyi.png)

### Kirovohrad
![](plots/per_oblast/horizon_eval_kirovohrad.png)

### Kyiv
![](plots/per_oblast/horizon_eval_kyiv.png)

### Kyiv City
![](plots/per_oblast/horizon_eval_kyiv_city.png)

### Luhansk
![](plots/per_oblast/horizon_eval_luhansk.png)

### Lviv
![](plots/per_oblast/horizon_eval_lviv.png)

### Mykolaiv
![](plots/per_oblast/horizon_eval_mykolaiv.png)

### Odesa
![](plots/per_oblast/horizon_eval_odesa.png)

### Poltava
![](plots/per_oblast/horizon_eval_poltava.png)

### Rivne
![](plots/per_oblast/horizon_eval_rivne.png)

### Sevastopol
![](plots/per_oblast/horizon_eval_sevastopol.png)

### Sumy
![](plots/per_oblast/horizon_eval_sumy.png)

### Ternopil
![](plots/per_oblast/horizon_eval_ternopil.png)

### Vinnytsia
![](plots/per_oblast/horizon_eval_vinnytsia.png)

### Volyn
![](plots/per_oblast/horizon_eval_volyn.png)

### Zakarpattia
![](plots/per_oblast/horizon_eval_zakarpattia.png)

### Zaporizhzhia
![](plots/per_oblast/horizon_eval_zaporizhzhia.png)

### Zhytomyr
![](plots/per_oblast/horizon_eval_zhytomyr.png)






