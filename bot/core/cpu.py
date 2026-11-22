from os import cpu_count


def allowed_cpus():
    try:
        from os import sched_getaffinity

        cpus = sorted(sched_getaffinity(0))
        if cpus:
            return cpus
    except (ImportError, OSError):
        pass
    return list(range(cpu_count() or 1))
