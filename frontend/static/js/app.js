async function refreshStatus() {
    const response = await fetch("/api/status");
    const data = await response.json();

    document.getElementById("systemState").textContent = data.state;
    document.getElementById("vehicleId").textContent = data.vehicle;

    if (data.emergency) {
        document.getElementById("requestStatus").textContent =
            "EMERGENCY REQUEST";
    } else {
        document.getElementById("requestStatus").textContent =
            "NO ACTIVE REQUEST";
    }
}

document.getElementById("approveBtn").addEventListener("click", () => {
    document.getElementById("systemState").textContent =
        "APPROVAL COMMAND READY";

    document.getElementById("signalState").textContent =
        "CORRIDOR APPROVAL REQUESTED";

    document.getElementById("latestEvent").textContent =
        "Operator pressed APPROVE CORRIDOR.";
});

document.getElementById("rejectBtn").addEventListener("click", () => {
    document.getElementById("systemState").textContent = "NORMAL";

    document.getElementById("signalState").textContent =
        "NORMAL TRAFFIC CYCLE";

    document.getElementById("latestEvent").textContent =
        "Operator pressed REJECT / RESOLVE.";
});

refreshStatus();