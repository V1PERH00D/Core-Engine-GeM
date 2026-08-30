def test_compliance_engine_package_imports() -> None:
    import compliance_engine
    import compliance_engine.anomalies
    import compliance_engine.audit
    import compliance_engine.flags
    import compliance_engine.ingestion
    import compliance_engine.models
    import compliance_engine.rules
    import compliance_engine.scoring
    import compliance_engine.verification

    assert compliance_engine.__doc__ is not None
