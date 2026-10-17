# OpenSubsurface calculation report

Run: `job-2efd90e47c444203`

Numerical checks: **PASS**. Geological fitness: **REQUIRES REVIEW**.

Initial oil in place; not recoverable reserves or a production forecast

```json
{
  "contacts": [
    {
      "name": "full",
      "contact_z_m": -19.0,
      "GRV": 4199.0,
      "GRV_oil_interval": 4199.0,
      "HCPV": 503.8800000000002,
      "NetRockVolume": 3359.2000000000007,
      "PV": 671.8400000000004,
      "STOIIP": 419.9000000000002
    },
    {
      "name": "partial",
      "contact_z_m": -10.0,
      "GRV": 4199.0,
      "GRV_oil_interval": 2210.0,
      "HCPV": 265.2000000000001,
      "NetRockVolume": 1768.0000000000005,
      "PV": 353.6000000000002,
      "STOIIP": 221.00000000000009
    },
    {
      "name": "dry",
      "contact_z_m": 0.0,
      "GRV": 4199.0,
      "GRV_oil_interval": 0.0,
      "HCPV": 0.0,
      "NetRockVolume": 0.0,
      "PV": 0.0,
      "STOIIP": 0.0
    }
  ],
  "assumptions": [
    "Synthetic uniform Cartesian geometry, exported GRDECL property controls",
    "Homogeneous phi=.2 NTG=.8 Sw=.25 Bo=1.2; not field data or a forecast"
  ],
  "missing": [],
  "failures": []
}
```

See report.html, report.json, volumes.csv and volumes.png for the full evidence.
