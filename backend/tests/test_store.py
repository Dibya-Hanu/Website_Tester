from app.core.models import CreateJob


def test_queue_claim_is_durable_and_ordered(store):
    first = store.create_job(CreateJob(url="http://lab.test:3000/"))
    second = store.create_job(CreateJob(url="http://lab.test:3000/about"))
    assert store.claim()["id"] == first["id"]
    assert store.claim()["id"] == second["id"]
    assert store.claim() is None
    assert store.get_job(first["id"])["attempts"] == 1


def test_interrupted_job_requeued_once(store):
    job = store.create_job(CreateJob(url="http://lab.test:3000/"))
    store.claim()
    store.recover()
    assert store.get_job(job["id"])["status"] == "queued"
    store.claim()
    store.recover()
    assert store.get_job(job["id"])["status"] == "failed"


def test_events_resume_from_last_id(store):
    job = store.create_job(CreateJob(url="http://lab.test:3000/"))
    eid = store.event(job["id"], {"type":"log","message":"first"})
    latest = store.event(job["id"], {"type":"log","message":"second"})
    events = store.events(job["id"], eid)
    assert len(events) == 1 and events[0]["id"] == latest
    assert events[0]["data"]["message"] == "second"


def test_queue_bound_and_parameterized_values(store):
    import pytest
    store.create_job(CreateJob(url="http://lab.test:3000/?q=';--"), max_queue=1)
    with pytest.raises(ValueError, match="full"):
        store.create_job(CreateJob(url="http://lab.test:3000/"), max_queue=1)
    assert len(store.list_jobs()) == 1
