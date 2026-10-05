801
802
803
804
805
806
807
808
809
810
811
812
813
814
815
816
817
818
819
820
821
822
823
824
825
826
827
828
829
830
831
832
833
834
835
836
837
838
839
840
841
842
843
844
845
846
847
848
849
850
851
852
853
854
855
856
857
858
859
860
861
862
863
864
865
866
867
868
869
870
871
872
873
874
875
876
877
878
879
880
881
882
883
884
885
886
887
888
889
890
891
892
893
894
895
896
897
898
899
900
901
902
903
904
905
906
907
908
909
910
911
912
913
914
915
916
917
918
919
920
921
922
923
924
                        "kind": new.status,
                        "opponent": new.opponent,
                        "date": new.date,
                        "detail": f"Official schedule status: {new.status.title()}",
                        "location": new.location,
                        "priority": 5 if new.status in {"CANCELED", "POSTPONED", "SUSPENDED"} else 4,
                    })

            if len(alerts) > 20:
                print(f"WARNING {sport}: suppressed {len(alerts)} alerts (safety threshold)", file=sys.stderr)
                alerts = []

            for alert in alerts:
                print(f"ALERT {sport}: {alert['kind']} — {alert.get('opponent', '')} — {alert.get('detail', '')}")
                schedule_alerted_keys.add((sport, normalized_opponent(alert.get("opponent", ""))))
                if topic:
                    send_ntfy(session, topic, alert, url)
                else:
                    print("  NTFY_TOPIC is not set; alert logged but not pushed", file=sys.stderr)
                total_alerts += 1
        else:
            print(f"BASELINE {sport}: saved {len(new_events)} home events")

        state["sources"][sport] = {
            "url": url,
            "schedule_label": new_label,
            "failure_count": 0,
            "last_error": "",
            "events": [asdict(e) for e in new_events],
        }
        time.sleep(0.20)

    # ----- Phase 2: official Liberty news archives (early warning) -----
    for source_name, archive_url, base_url in NEWS_SOURCES:
        old_news = state["news"].get(source_name, {})
        seen_urls = list(old_news.get("seen_urls", []))
        initialized = bool(old_news.get("initialized", False))
        try:
            items = fetch_archive_items(session, archive_url, base_url)
        except Exception as exc:
            news_errors += 1
            print(f"NEWS ERROR {source_name}: {exc}", file=sys.stderr)
            # Optional layer: preserve its prior state and continue without affecting schedules.
            state["news"][source_name] = {
                **old_news,
                "archive_url": archive_url,
                "last_error": clean(str(exc))[:300],
            }
            continue

        current_urls = [item.url for item in items]
        if not initialized:
            # Silent one-time baseline so installing Phase 2 does not alert on old stories.
            state["news"][source_name] = {
                "archive_url": archive_url,
                "initialized": True,
                "last_error": "",
                "seen_urls": merge_seen_urls(current_urls, seen_urls),
            }
            print(f"NEWS BASELINE {source_name}: saved {len(current_urls)} current stories")
            continue

        unseen = [item for item in items if item.url not in set(seen_urls)]
        processed_urls: list[str] = []
        # Archives are newest-first; process oldest unseen story first for sensible alert order.
        for item in reversed(unseen):
            try:
                title, body = fetch_article(session, item)
            except Exception as exc:
                news_errors += 1
                print(f"NEWS ARTICLE ERROR {item.url}: {exc}", file=sys.stderr)
                continue  # leave unseen so the next 10-minute run retries it

            processed_urls.append(item.url)
            disruption = detect_news_disruption(title, body)
            if not disruption:
                continue

            match = match_news_to_home_event(item, f"{title} {body}", home_events)
            if not match:
                print(f"NEWS IGNORE {source_name}: disruption language but no upcoming home-event match — {title}")
                continue

            sport, event = match
            event_key = (sport, normalized_opponent(event.opponent))
            if event_key in schedule_alerted_keys:
                print(f"NEWS DUPLICATE SUPPRESSED {sport}: schedule already alerted this run — {title}")
                continue

            alert = {
                "sport": sport,
                "kind": "EARLY WARNING",
                "opponent": event.opponent,
                "date": event.date,
                "detail": f"Official {source_name} story contains {disruption.lower()} language: {title}",
                "location": event.location,
                "priority": 5,
            }
            print(f"NEWS ALERT {sport}: {disruption} — {event.opponent} — {title}")
            if topic:
                send_ntfy(session, topic, alert, item.url)
            else:
                print("  NTFY_TOPIC is not set; news alert logged but not pushed", file=sys.stderr)
            total_alerts += 1

        state["news"][source_name] = {
            "archive_url": archive_url,
            "initialized": True,
            "last_error": "",
            "seen_urls": merge_seen_urls(processed_urls, seen_urls),
        }
        time.sleep(0.20)

    save_state(state)
    print(
        f"Done. alerts={total_alerts}, schedule_errors={source_errors}, "
        f"news_errors={news_errors}, schedule_sources={len(SOURCES)}, news_sources={len(NEWS_SOURCES)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
