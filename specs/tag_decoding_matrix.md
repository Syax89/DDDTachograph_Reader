# Tag Decoding Matrix

This matrix is the operational backlog for full DDD semantic decoding. Status values:

- `complete`: decoded, registered, and test-covered.
- `partial`: decoded but incomplete, heuristic, or weakly tested.
- `raw`: recognized but stored without semantic decoding.
- `missing`: expected but not implemented or not dispatched.

## High-Priority Backlog

| Tag | Name | Generation | Scope | Encoding | Status | Confidence | Priority | Next Owner | Source / Note |
|---:|---|---|---|---|---|---|---|---|---|
| `0x052C` | VuDetailedSpeedData | G2.2 | VU | RecordArray | partial | HIGH | P0 | G2.2 Parser Agent | Decoder registered; conservative 64-byte timestamp + speed samples; needs golden validation |
| `0x0532` | G22 SensorExternalGNSSCoupledData | G2.2 | VU | RecordArray | complete | HIGH | P0 | G2.2 Parser Agent | Reuses G2 `0x0511` structure; unit tested |
| `0x0533` | G22 SensorPairedData | G2.2 | VU | RecordArray | complete | HIGH | P0 | G2.2 Parser Agent | Reuses G2 `0x0510` structure; unit tested |
| `0x052D` | VuOverSpeedingEventData | G2.2 | VU | RecordArray | missing | MEDIUM | P1 | G2.2 Parser Agent | Estimated structure in `g22_verification_status.md` |
| `0x052E` | VuOverSpeedingControlData | G2.2 | VU | RecordArray | missing | MEDIUM | P1 | G2.2 Parser Agent | Estimated structure in `g22_verification_status.md` |
| `0x052F` | VuTimeAdjustmentGNSSRecord | G2.2 | VU | RecordArray | missing | MEDIUM | P1 | G2.2 Parser Agent | Estimated 8-byte records |
| `0x0530` | VuPowerSupplyInterruptionData | G2.2 | VU | RecordArray | missing | MEDIUM | P1 | G2.2 Parser Agent | Estimated 90-byte records |
| `0x0531` | VuSensorFaultData | G2.2 | VU | RecordArray | missing | LOW | P1 | G2.2 Parser Agent | Requires source confirmation |
| `0x960F` | GNSS Auth Data | G2.2 | Security | BER-TLV | raw | LOW | P1 | Security Agent | Requires JRC/source confirmation |
| `0x6399` | Load/Unload Auth | G2.2 | Security | BER-TLV | raw | LOW | P1 | Security Agent | Requires JRC/source confirmation |
| `0x7601` | G1 VU TechnicalData | G1 | VU | STAP/record | partial | MEDIUM | P1 | G1 Parser Agent | Annex 1B VU container, currently partly heuristic |
| `0x7602` | G1 VU Activities | G1 | VU | STAP/record | partial | MEDIUM | P1 | G1 Parser Agent | Replace heuristic scanning with deterministic records |
| `0x7603` | G1 VU EventsFaults | G1 | VU | STAP/record | partial | MEDIUM | P1 | G1 Parser Agent | Replace heuristic scanning with deterministic records |
| `0x7605` | G1 VU DetailedSpeed | G1 | VU | STAP/record | missing | MEDIUM | P2 | G1 Parser Agent | Documented in specs, absent from registry |
| `0x0508` | G1 ControlActivityData | G1 | Card | STAP | partial | MEDIUM | P2 | G1 Parser Agent | Existing decoder needs spec alignment |
| `0x050C` | CalibrationData | all | Card/VU | STAP/BER | partial | MEDIUM | P2 | G1/G2 Parser Agents | Layout differs by generation |
| `0x0222` | EF GNSS Places | G2 | Card | BER-TLV | raw | MEDIUM | P2 | G2 Parser Agent | Registered without decoder |
| `0x0223` | EF GNSS Accumulated Position | G2 | Card | BER-TLV | raw | MEDIUM | P2 | G2 Parser Agent | Registered without decoder |

## G2.2 Implemented But Needs Verification

| Tag | Name | Status | Confidence | Required Action |
|---:|---|---|---|---|
| `0x0525` | G22 GNSS Accumulated Driving | partial | MEDIUM | Confirm byte layout and add golden assertions |
| `0x0526` | G22 Load/Unload Operations | partial | LOW | Confirm record layout and auth relation |
| `0x0527` | G22 Trailer Registrations | partial | LOW | Confirm record layout |
| `0x0528` | G22 GNSS Enhanced Places | partial | MEDIUM | Confirm mapping and avoid conflict with `0x0225` |
| `0x0529` | G22 Load Sensor Data | partial | LOW | Confirm record layout |
| `0x052A` | G22 Border Crossings | partial | LOW | Confirm record layout |
| `0x052B` | VuControllerIdentification | partial | MEDIUM | Add structured decoder and tests |

## Certificate / Signature Backlog

| Tag | Name | Generation | Status | Required Action |
|---:|---|---|---|---|
| `0x0103` | G2 CardCertificate | G2 | raw | Decode certificate structure and expose fields |
| `0x0104` | G2 MemberStateCertificate | G2 | raw | Decode certificate structure and expose fields |
| `0xC100` | G1 CardCertificate | G1 | raw | Decode certificate structure and expose fields |
| `0xC108` | G1 CA Certificate | G1 | raw | Decode certificate structure and expose fields |
| `0xC101` | G2 CardCertificate | G2 | raw | Decode certificate structure and expose fields |
| `0xC109` | G2 CA Certificate | G2 | raw | Decode certificate structure and expose fields |
| `0xC102` | G22 CardCertificate | G2.2 | raw | Decode certificate structure and expose fields |
| `0xC10A` | G22 CA Certificate | G2.2 | raw | Decode certificate structure and expose fields |

## Real-File Baseline

Current semantic baseline is stored in `specs/semantic_coverage_report.json`. The historical tracked-coverage report remains in `specs/coverage_report.json`. The QA gate is that `unparsed_bytes` must not increase for any listed file unless the semantic baseline is intentionally regenerated with a documented reason.
