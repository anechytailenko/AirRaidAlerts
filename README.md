

# Train process 
![](/demo/train_01.png)

![](/demo/train_02.png)

All training and validation plots can be found here : https://wandb.ai/anna-nechytailenko-kyiv-school-of-economics/airraid-stgnn/workspace?nw=nwuserannanechytailenko

# Test metrics

| k | test_pr_auc | test_brier |
| --- | --- | --- |
| 1 | 0.45272 | 0.18412 |
| 2 | 0.42864 | 0.20313 |
| 3 | 0.42758 | 0.20542 |
| 4 | 0.43181 | 0.20959 |
| 5 | 0.44558 | 0.20952 |
| 6 | 0.43404 | 0.22976 |



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



# Web Demo


# Analysis

![](/demo/web_01.png)

# Prediction

![](/demo/web_02.png)
