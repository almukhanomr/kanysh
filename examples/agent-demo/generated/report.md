# OpenSubsurface calculation report

Run: `job-9ad61541bb9c410c`

Numerical checks: **PASS**. Geological fitness: **REQUIRES REVIEW**.

Initial oil in place; not recoverable reserves or a production forecast

```json
{
  "contacts": [
    {
      "name": "full",
      "contact_z_m": -1040.0,
      "GRV": 20000000.0,
      "GRV_oil_interval": 20000000.0,
      "HCPV": 2400000.0,
      "NetRockVolume": 15999999.999999998,
      "PV": 3200000.0000000005,
      "STOIIP": 2000000.0
    },
    {
      "name": "half",
      "contact_z_m": -1030.0,
      "GRV": 20000000.0,
      "GRV_oil_interval": 10000000.0,
      "HCPV": 1200000.0,
      "NetRockVolume": 7999999.999999999,
      "PV": 1600000.0000000002,
      "STOIIP": 1000000.0
    },
    {
      "name": "dry",
      "contact_z_m": -1020.0,
      "GRV": 20000000.0,
      "GRV_oil_interval": 0.0,
      "HCPV": 0.0,
      "NetRockVolume": 0.0,
      "PV": 0.0,
      "STOIIP": 0.0
    }
  ],
  "assumptions": [
    "Synthetic analytical control, not field data or a production forecast",
    "Horizontal horizon, homogeneous reservoir below it, constant Bo and horizontal OWC"
  ],
  "missing": [],
  "failures": []
}
```

See report.html, report.json, volumes.csv and volumes.png for the full evidence.
