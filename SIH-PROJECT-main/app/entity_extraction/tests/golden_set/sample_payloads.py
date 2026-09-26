# tests/golden_set/sample_payloads.py

# TEST CASE 1: Compliant Medium Enterprise
SAMPLE_COMPLIANT_BIDDER = {
    "submission_id": "sub_compliant_001",
    "pages": [
        {
            "page_number": 1,
            "detected_category": "TAX_COMPLIANCE",
            "raw_text": (
                "GOVERNMENT OF INDIA - FORM GST REG-06\n"
                "Registration Certificate\n"
                "GSTIN: 27AAACI1234F1Z5\n"
                "Legal Name: BHARAT INFRASTRUCTURE SOLUTIONS PRIVATE LIMITED\n"
                "Trade Name: BHARAT INFRA\n"
                "PAN: AAACI1234F\n"
                "Constitution of Business: Private Limited Company\n"
                "PAN-Aadhaar Linked and Verified.\n"
            ),
            "blocks": [
                {"bbox": [50.0, 100.0, 300.0, 120.0], "text": "GSTIN: 27AAACI1234F1Z5"},
                {"bbox": [50.0, 130.0, 200.0, 150.0], "text": "PAN: AAACI1234F"}
            ]
        },
        {
            "page_number": 2,
            "detected_category": "AUDITED_FINANCIALS",
            "raw_text": (
                "INDEPENDENT AUDITOR'S REPORT - BALANCE SHEET & P&L\n"
                "CIN: U45200MH2015PTC261234\n"
                "Director DIN: 08912345, DIN: 07823456\n"
                "Financial Turnovers:\n"
                "FY 2022-23: INR 12.50 Cr\n"
                "FY 2023-24: INR 15.80 Cr\n"
                "FY 2024-25: INR 18.20 Cr\n"
                "Net Worth: INR 26.50 Crores\n"
                "Solvency Status: Positive\n"
            ),
            "blocks": [
                {"bbox": [60.0, 200.0, 350.0, 240.0], "text": "FY 2024-25: INR 18.20 Cr"},
                {"bbox": [60.0, 250.0, 300.0, 270.0], "text": "Net Worth: INR 26.50 Crores"}
            ]
        },
        {
            "page_number": 3,
            "detected_category": "STATUTORY_CERTIFICATES",
            "raw_text": (
                "UDYAM REGISTRATION CERTIFICATE\n"
                "Udyam Registration Number: UDYAM-MH-12-0019842\n"
                "Enterprise Category: Medium\n"
                "Major Activity: Manufacturing (NIC Code: 28)\n"
                "EPFO Establishment Code: MHBAN0012345000\n"
                "ESIC Registration Code: 31000123450000101\n"
                "CA Turnover Certificate UDIN: 24045678AAAAAA1234\n"
                "Make in India Self Declaration: Declared Local Content: 68.5% (Class-I Local Supplier)\n"
                "DigiLocker Verified Document Reference: DL-DOC-2026-9912\n"
            ),
            "blocks": [
                {"bbox": [55.0, 80.0, 320.0, 100.0], "text": "UDYAM-MH-12-0019842"},
                {"bbox": [55.0, 180.0, 300.0, 200.0], "text": "UDIN: 24045678AAAAAA1234"}
            ]
        }
    ]
}

# TEST CASE 2: DPIIT Startup / Small Enterprise
SAMPLE_STARTUP_BIDDER = {
    "submission_id": "sub_startup_002",
    "pages": [
        {
            "page_number": 1,
            "detected_category": "STARTUP_COMPLIANCE",
            "raw_text": (
                "MINISTRY OF COMMERCE AND INDUSTRY - DPIIT RECOGNITION\n"
                "Startup India Certificate\n"
                "DPIIT Recognition Number: DIPP88421\n"
                "Company: QUICKBOT AUTOMATION PRIVATE LIMITED\n"
                "PAN: ABBCQ5432G\n"
                "GSTIN: 27ABBCQ5432G1Z9\n"
                "UDYAM-MH-33-0099881 (Enterprise Category: Micro)\n"
            ),
            "blocks": [{"bbox": [50.0, 100.0, 250.0, 120.0], "text": "DPIIT: DIPP88421"}]
        },
        {
            "page_number": 2,
            "detected_category": "AUDITED_FINANCIALS",
            "raw_text": (
                "AUDITED FINANCIAL STATEMENT\n"
                "FY 2023-24: INR 450 Lakhs\n"
                "FY 2024-25: INR 620 Lakhs\n"
                "Net Worth: INR 2.10 Crores\n"
                "Local Content: 85.0% (Class-I Local Supplier)\n"
            ),
            "blocks": [{"bbox": [50.0, 200.0, 280.0, 220.0], "text": "FY 2024-25: INR 620 Lakhs"}]
        }
    ]
}

# TEST CASE 3: Discrepant Shell Company (Lacks UDIN, Shortfall Turnover)
SAMPLE_DISCREPANT_BIDDER = {
    "submission_id": "sub_fraud_003",
    "pages": [
        {
            "page_number": 1,
            "detected_category": "TAX_COMPLIANCE",
            "raw_text": (
                "TAX FILING RECORD\n"
                "Legal Name: SHELL TRADING CORP\n"
                "GSTIN: 07FAKEP9999F1Z1\n"
                "PAN: FAKEP9999F\n"
                "Status: SUSPENDED\n"
            ),
            "blocks": [{"bbox": [50.0, 100.0, 250.0, 120.0], "text": "GSTIN: 07FAKEP9999F1Z1"}]
        },
        {
            "page_number": 2,
            "detected_category": "AUDITED_FINANCIALS",
            "raw_text": (
                "BALANCE SHEET\n"
                "FY 2023-24: INR 1.20 Cr\n"
                "FY 2024-25: INR 1.80 Cr\n"
                "Net Worth: INR -0.50 Crores\n"
                "CA UDIN: INVALID_UDIN_123\n"
                "Local Content: 12% (Non-Local Supplier)\n"
            ),
            "blocks": [{"bbox": [50.0, 200.0, 250.0, 220.0], "text": "Local Content: 12%"}]
        }
    ]
}