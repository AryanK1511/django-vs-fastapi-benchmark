def bytes_human(n: int) -> str:
    x = float(n)
    if x < 1024:
        return f"{int(x)} B"
    for suffix in ("KiB", "MiB", "GiB", "TiB"):
        x /= 1024.0
        if x < 1024 or suffix == "TiB":
            return f"{x:.2f} {suffix}"
    return f"{int(n)} B"


def percent_of_host(p: float) -> str:
    return f"{p:.1f}% of host RAM"


def host_memory_sentence(vm_total: int, vm_avail: int, vm_percent: float) -> str:
    return (
        f"Host memory: {vm_percent:.1f}% in use; "
        f"{bytes_human(vm_avail)} free of {bytes_human(vm_total)} total"
    )


def host_cpu_sentence(cpu_pct: float) -> str:
    return f"Host CPU (all cores, snapshot): {cpu_pct:.1f}% busy"
