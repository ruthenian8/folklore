class ESSearchBackend:
    def __init__(
        self,
        *,
        find_sentences_json,
        add_sent_to_session,
        sent_viewer,
        settings,
        get_session_data,
        set_session_data,
        sync_page_data,
        build_context,
    ):
        self._find_sentences_json = find_sentences_json
        self._add_sent_to_session = add_sent_to_session
        self._sent_viewer = sent_viewer
        self._settings = settings
        self._get_session_data = get_session_data
        self._set_session_data = set_session_data
        self._sync_page_data = sync_page_data
        self._build_context = build_context

    def search_sentences(self, request_args, page, session_data):
        if page < 0:
            self._set_session_data("page_data", {})
            page = 0
        hits = self._find_sentences_json(page=page)
        self._add_sent_to_session(hits)
        hits_processed = self._sent_viewer.process_sent_json(
            hits,
            translit=self._get_session_data("translit"),
        )
        hits_processed["page"] = self._get_session_data("page")
        hits_processed["page_size"] = self._get_session_data("page_size")
        hits_processed["languages"] = self._settings["languages"]
        hits_processed["media"] = self._settings["media"]
        hits_processed["subcorpus_enabled"] = False
        hits_processed["n_sentences"] = hits_processed["n_sentences"]["value"]
        if "subcorpus_enabled" in hits:
            hits_processed["subcorpus_enabled"] = True
        self._sync_page_data(hits_processed["page"], hits_processed)
        max_page_number = (min(hits_processed["n_sentences"], 1000) - 1) // hits_processed[
            "page_size"
        ] + 1
        hits_processed["too_many_hits"] = 1000 < hits_processed["n_sentences"]
        return {
            "data": hits_processed,
            "max_page_number": max_page_number,
        }

    def get_sentence_context(self, n, session_data):
        return self._build_context(n)
