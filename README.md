# KSP Crime Intelligence Platform

> **AI-Driven Crime Analytics & Visualization Platform**  
> Developed for the **Karnataka State Police (KSP) Datathon 2026**

**Live Demo:** https://kspcrimeintelligence-50044296851.development.catalystappsail.in/

---

## Team – "My Internet is Cooked"

| Name | Role |
|------|------|
| **Bhakti Chand Tak** | Team Lead, Backend & Integration |
| **Baibhav Singh** | Machine Learning & Data Analysis |
| **Rajuram** | Data Engineering & Synthetic Dataset |
| **Kaushik Rongpi** | Frontend & UI Development |

---

# Project Overview

The Karnataka State Police currently relies on fragmented crime records and manual reporting systems, making it difficult to identify crime hotspots, detect criminal networks, and analyze emerging crime trends efficiently.

Our solution, **KSP Crime Intelligence Platform**, is an AI-powered crime analytics dashboard designed to assist law enforcement with data-driven decision making. The platform combines predictive analytics, interactive visualizations, geospatial mapping, and criminal network analysis into a single dashboard.

Since no official dataset was provided during the hackathon, we generated a realistic synthetic crime dataset to demonstrate the complete end-to-end workflow while maintaining privacy and reproducibility.

---

# Problem Statement

Build an **AI-Driven Crime Analytics & Visualization Platform** capable of:

- Visualizing crime patterns across Karnataka.
- Identifying crime hotspots.
- Predicting future crime trends.
- Detecting criminal associations.
- Supporting proactive policing using AI and data analytics.

---

# Key Features

## Interactive Crime Dashboard

- District-wise crime analysis
- Police station level insights
- Interactive maps
- Crime distribution charts
- Dynamic filtering

---

## Crime Hotspot Detection

- Detect emerging crime hotspots
- Identify high-risk locations
- Spatial visualization using maps

---

## Crime Trend Prediction

- Forecast future crime counts
- Predict serious offence probability
- Trend analysis using Machine Learning

---

## Criminal Network Analysis

- Visualize repeat offenders
- Discover hidden criminal associations
- Network graph representation

---

## Scenario Simulator

- Simulate different situations
- Analyze effect of holidays
- Explore crime category trends
- Time-based forecasting

---

## Fairness & Model Evaluation

- Fairness monitoring
- Model performance evaluation
- Statistical validation
- Confidence indicators

---

# Technology Stack

## Frontend

- HTML5
- CSS3
- JavaScript
- Chart.js
- Leaflet.js
- Cytoscape.js

---

## Backend

- Python
- FastAPI
- Zoho Catalyst AppSail

---

## Machine Learning

- Scikit-learn
- Pandas
- NumPy
- SciPy

---

## Data

- Synthetic Crime Dataset (~80,000 FIR Records)
- 31 Districts
- 164 Police Stations

---

## Deployment

- Zoho Catalyst AppSail
- Docker

---

# Repository Structure

```text
ksp-crime-intelligence/
│
├── MasterCodeBase/
│   ├── ksp_pipeline_v8_final.py
│   ├── server.py
│   ├── index.html
│   ├── pipeline_outputs/
│   └── reports/
│
├── data/
│   ├── Dataset_grounded.csv
│   ├── ksp_station_registry_v8.csv
│   └── dashboard_data_v8.json
│
├── backend/
│
├── frontend/
│
├── docs/
│
├── presentation/
│
└── README.md
```

---

# Getting Started

### Clone the Repository

```bash
git clone https://github.com/bhaktictak/ksp-crime-intelligence.git

cd ksp-crime-intelligence
```

---

### Install Dependencies

```bash
cd MasterCodeBase

pip install -r requirements.txt
```

---

### Run the Pipeline

```bash
python ksp_pipeline_v8_final.py
```

This generates the processed dashboard data and launches the complete analytical pipeline.

---

# Project Workflow

```text
Synthetic Dataset
        │
        ▼
Data Cleaning & Validation
        │
        ▼
Feature Engineering
        │
        ▼
Machine Learning Models
        │
        ▼
Crime Analytics
        │
        ▼
Interactive Dashboard
        │
        ▼
Deployment on Zoho Catalyst
```

---

# Challenges Faced

- No official crime dataset was provided.
- Designing a realistic synthetic dataset.
- Building an end-to-end AI pipeline within the hackathon timeline.
- Integrating multiple analytical modules into a single dashboard.
- Deploying the complete solution on Zoho Catalyst.

---

# Future Scope

- Live integration with official police databases.
- Real-time crime monitoring.
- Mobile application for officers.
- Advanced predictive models.
- Secure authentication and role-based access.
- Continuous model retraining.

---

# Demo

### Live Dashboard

https://kspcrimeintelligence-50044296851.development.catalystappsail.in/

---

# Documentation

Project documentation is available inside the **docs/** folder.

---

# Disclaimer

This project uses **synthetic data** created exclusively for demonstration and educational purposes during the KSP Datathon 2026.

It does **not** represent real Karnataka Police records and should not be used for operational policing decisions.

---
