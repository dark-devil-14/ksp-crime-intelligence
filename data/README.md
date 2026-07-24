# Data Folder README

This folder contains the main data assets used by the KSP Crime Intelligence project. The files here are used to power crime analysis, station lookup, and dashboard visualizations.

## Files
| File | Purpose |
| --- | --- |
| `Dataset_grounded.csv` | Case-level crime records with offence, location, date, people, and outcome details. |
| `ksp_station_registry_v8.csv` | Police station registry and location reference for mapping and filters. |
| `dashboard_data_v8.json` | Prepared data for charts, summaries, and frontend widgets. |

## What This Data Supports
- crime trend analysis by district, station, beat, and time
- hotspot and location-based mapping
- Repeat offender tracking
- Predictive risk scoring
- station-level reference lookup for dashboards and filters
- case outcome and offence pattern analysis

## Why This Folder Matters
The crime dataset is the main source of truth for case records, the station registry adds clean reference data for mapping and filtering, and the dashboard JSON helps the frontend load ready-to-use analytics without heavy processing at runtime.

## Field Summary
### Dataset_grounded.csv
| Field Group | Key Columns |
| --- | --- |
| Case metadata | `CaseMasterID`, `CrimeNo`, `CaseNo`, `CaseStatus` |
| Offence details | `CaseCategory`, `GravityOffence`, `CrimeMajorHead`, `CrimeMinorHead`, `Act`, `Section` |
| Jurisdiction details | `InvestigatingAgency`, `PoliceRange`, `Division`, `DistrictID`, `DistrictName`, `PoliceStationID`, `PoliceStationName` |
| Location data | `StationLatitude`, `StationLongitude`, `BeatName`, `Latitude`, `Longitude` |
| Date fields | `IncidentFromDate`, `IncidentToDate`, `CrimeRegisteredDate`, `InfoReceivedPSDate` |
| Person details | `ComplainantAge`, `ComplainantOccupation`, `ComplainantReligion`, `ComplainantCaste`, `ComplainantGender`, `VictimAge`, `VictimGender`, `VictimPolice`, `NAccused`, `AccusedMasterID`, `AccusedAge`, `AccusedGender`, `AccusedCaste` |
| Investigation and outcome | `PriorOffences`, `PropertyInvolved`, `PropertyValue_INR`, `InjuryPresent`, `ArrestMade`, `ChargeSheeted` |

### ksp_station_registry_v8.csv
| Field Group | Key Columns |
| --- | --- |
| District and station IDs | `DistrictID`, `DistrictName`, `PoliceStationID`, `PoliceStationName` |
| Station location | `StationLatitude`, `StationLongitude` |
| Coverage context | `StationPopulation` |
| Data cleanup flag | `CoordinateAdjustedToLand` |

### dashboard_data_v8.json
This file usually contains pre-aggregated counts, summary metrics, and chart-ready values for the frontend.

## Notes
- Treat these files as project data assets, not application code.
- Some records may contain sensitive information and should be cleaned or anonymized before public release.
