# Working browser verification

The application was exercised locally on macOS with Python 3.12, through the actual browser UI and fictional demo data. These screenshots show the working product, not generated mockups.

- Compared three suppliers: unknown shipping prevented ranking.
- Compared the two complete offers: exact normalized totals and lowest-cost highlight.
- Uploaded the authored quote image through the browser; actual RapidOCR returned a reviewable draft and original-image evidence.

All six apps were checked at a 390×844 viewport; this app's document width was 390px with no horizontal overflow. The temporary viewport was reset after the check. The fresh final app load reported no JavaScript errors. Desktop and mobile captures can show different points in the walkthrough.

Automated regression suite: **69 passing tests**. The README describes test scope and measured coverage. These checks do not establish production scale or complete security coverage.
