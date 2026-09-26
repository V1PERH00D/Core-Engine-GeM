from tasks import process_entity_extraction_job

def test_full_extraction_pipeline():
    sample_payload = {
        "submission_id": "test_submission_01",
        "pages": [
            {
                "page_number": 1,
                "raw_text": "GSTIN: 27AAACI1234F1Z5 PAN: AAACI1234F UDYAM-MH-12-0012345",
                "blocks": [{"bbox": [50, 100, 200, 120], "text": "GSTIN: 27AAACI1234F1Z5"}]
            },
            {
                "page_number": 2,
                "raw_text": "Financials: FY 2022-23: INR 12.50 Cr. FY 2023-24: INR 15.00 Cr. Net Worth: INR 20.0 Cr. Local Content: 65%",
                "blocks": [{"bbox": [60, 200, 300, 220], "text": "Net Worth: INR 20.0 Cr"}]
            }
        ]
    }
    
    result = process_entity_extraction_job(sample_payload)
    # The job returns a per-bidder envelope; bidder 0 holds the payload built
    # directly from the supplied pages.
    data = result["bidders"][0]["extracted_entities"]

    assert data["gst"]["gstin"] == "27AAACI1234F1Z5"
    assert data["pan_itr"]["pan_number"] == "AAACI1234F"
    assert data["make_in_india"]["supplier_class"] == "Class-I Local Supplier"
    assert len(data["balance_sheet"]["turnover_records"]) == 2
    print("Pipeline integration tests passed.")

if __name__ == "__main__":
    test_full_extraction_pipeline()