from regex_patterns import extract_statutory_tokens

def test_statutory_token_extraction():
    text = "Bidder PAN is AAACI1234F, GSTIN is 27AAACI1234F1Z5, and UDIN is 24045678AAAAAA1234."
    tokens = extract_statutory_tokens(text)
    # extract_statutory_tokens returns the first match per token key
    # (uppercase-normalized scalar), with the full match list available
    # under ``all_matches``.
    assert tokens["pan"] == "AAACI1234F"
    assert tokens["gstin"] == "27AAACI1234F1Z5"
    assert tokens["udin"] == "24045678AAAAAA1234"
    assert tokens["all_matches"]["pan"] == ["AAACI1234F"]
    print("Regex unit tests passed.")

if __name__ == "__main__":
    test_statutory_token_extraction()