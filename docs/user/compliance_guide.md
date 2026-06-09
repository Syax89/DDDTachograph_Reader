# Compliance Guide — EU 561/2006

This guide explains the driving and rest rules enforced by the compliance engine, how infractions are detected, and how to interpret the results.

---

## Overview of EU Regulation 561/2006

EU 561/2006 sets limits on driving times and minimum rest periods for professional drivers of vehicles over 3.5 tonnes (or vehicles carrying 9+ persons). The rules aim to improve road safety and driver working conditions.

---

## The Rules in Simple Terms

### 1. Daily Driving Limit (Art. 6.1)

| Rule | Limit |
|------|-------|
| Maximum driving per day | **9 hours** |
| Extended driving (max 2x per week) | **10 hours** |

The "day" is the period between two daily rest periods. The compliance engine checks that no shift exceeds 9 hours of driving, and that the 10-hour extension is used at most twice per calendar week (Monday–Sunday).

### 2. Continuous Driving and Breaks (Art. 7)

| Rule | Limit |
|------|-------|
| Maximum continuous driving | **4 hours 30 minutes** (270 min) |
| Required break after 4.5h driving | **45 minutes** |
| Split break option | **15 min + 30 min** (in that order) |

The compliance engine tracks the driving accumulator. When it exceeds 270 minutes without a qualifying break, an infraction is raised. A break of 45 minutes or more fully resets the accumulator. The split break (15 min first, then 30 min) is recognized per EU rules.

### 3. Daily Rest (Art. 8.2)

| Rule | Limit |
|------|-------|
| Regular daily rest | **11 hours** (660 min) |
| Reduced daily rest | **9 hours** (540 min) |
| Maximum reduced rests between weekly rests | **3** |

Within any 24-hour window from the start of activities, at least 9 hours of rest must be completed. The engine analyzes every 24-hour sliding window and checks whether the rest inside it meets the minimum. It also tracks reduced rests and flags when more than 3 occur between consecutive weekly rests.

### 4. Weekly Rest (Art. 8.6)

| Rule | Limit |
|------|-------|
| Regular weekly rest | **45 hours** |
| Reduced weekly rest | **24 hours** |
| Maximum working period between weekly rests | **6 × 24 hours** (144 hours) |

The engine identifies rests of at least 24 hours and checks that no more than 144 hours pass between them. It also tracks reduced weekly rests and checks whether the missing hours are compensated within 3 weeks.

### 5. Bi-Weekly Driving Limit (Art. 6.2)

| Rule | Limit |
|------|-------|
| Total driving in 2 consecutive weeks | **90 hours** |

The engine sums driving time across consecutive Monday–Sunday weeks and flags any pair exceeding 90 hours. It also checks the single-week limit (56 hours).

---

## Severity Levels

Every infraction is assigned a severity level based on how far the limit was exceeded:

### Continuous Driving (ECCESSO_GUIDA_CONTINUA)

| Excess | Severity | Fine Range |
|--------|----------|------------|
| Up to 30 minutes | **MI** (Minor) | €167 – €668 |
| 31–90 minutes | **SI** (Serious) | €334 – €1,336 |
| Over 90 minutes | **MSI** (Most Serious) | €445 – €1,780 |

### Daily Rest (RIPOSO_GIORNALIERO_INSUFFICIENTE)

| Shortfall | Severity | Fine Range |
|-----------|----------|------------|
| Up to 60 minutes | **MI** (Minor) | €167 – €668 |
| 61–120 minutes | **SI** (Serious) | €334 – €1,336 |
| Over 120 minutes | **MSI** (Most Serious) | €445 – €1,780 |

---

## Infraction Type Codes

| Code | Meaning |
|------|---------|
| `ECCESSO_GUIDA_CONTINUA` | Exceeded 4.5h continuous driving without adequate break |
| `RIPOSO_GIORNALIERO_INSUFFICIENTE` | Insufficient daily rest within the 24-hour window |
| `ECCESSO_GUIDA_GIORNALIERA` | Exceeded 9h (or 10h) daily driving limit |
| `ECCESSO_ESTENSIONI_GUIDA_SETTIMANALI` | Used the 10h extension more than twice in a week |
| `SUPERAMENTO_6_PERIODI_24H` | More than 144 hours between weekly rests |
| `MANCATA_COMPENSAZIONE_SETTIMANALE` | Reduced weekly rest not compensated within 3 weeks |
| `ECCESSO_GUIDA_BISETTIMANALE` | Exceeded 90h driving in 2 consecutive weeks |
| `ECCESSO_GUIDA_SETTIMANALE` | Exceeded 56h driving in a single week |
| `ECCESSO_RIPOSI_RIDOTTI` | More than 3 reduced daily rests between weekly rests |

---

## Reading the Infractions Table

In the GUI's **Infrazioni** tab:

1. **Data**: The date the violation occurred. Click the column header to sort chronologically.
2. **Tipo Infrazione**: The violation code — focus on **MSI** severity items first.
3. **Severità**: Color-code mentally: Red = MSI, Orange = SI, Yellow = MI.
4. **Descrizione**: Reads the specific numbers (e.g., "Guida continua di 295 min..." — you drove 25 minutes too long).

The fines banner shows the cumulative estimate. The range reflects the minimum and maximum per Italian law. Actual fines are determined by enforcement authorities.

---

## Important Legal Note

The fine estimates are based on the Italian Highway Code (Art. 174 C.d.S.) and EU Regulation 561/2006. They are **informational only** and have no legal value. Reports must be verified by a qualified professional for official use.
