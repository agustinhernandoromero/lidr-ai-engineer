"""Grounded generation (session 11): estimates cited line by line, verified after generation.

    retrieve (hybrid)  ->  sources tagged with their chunk id  ->  LLM (JSON schema)
                       ->  verify_citations (every cited id must have been retrieved)
"""
