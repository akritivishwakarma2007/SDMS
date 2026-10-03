from sdms.core.sources.interfaces import Frame
def send(ledger, box, truth, tid, quality="ok"):
    payload, sig = box.process(Frame(f"img-{tid}".encode(), tid, {"truth": truth, "quality": quality}))
    return payload, sig, ledger.ingest(payload, sig)


def fill(ledger, box, n=6):
    for i in range(n):
        send(ledger, box, ["100"], f"t{i}")
