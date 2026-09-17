"""LoadGate: pause labelling while the machine is busy, resume when free.

Busy means low free VRAM (the binding constraint for local inference) or
high GPU utilization. Checked fresh every pass; free memory barely moves
second to second, so no averaging or hysteresis is needed. Anything
unmeasurable fails open toward idle so monitoring gaps never stall
labelling.
"""
import json
import subprocess
import urllib.request


class LoadGate:
    def __init__(self, ollama_url, model, max_gpu_util=40, min_free_mb=5500,
                 idle_gpu_util=10):
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.max_gpu_util = max_gpu_util
        self.min_free_mb = min_free_mb
        self.idle_gpu_util = idle_gpu_util
        self.was_busy = False

    def gpu_status(self):
        """Returns (util_percent, free_mb), each None if unmeasurable."""
        try:
            # CREATE_NO_WINDOW: nvidia-smi is a console app; without this
            # every check flashes a visible window (notably from pythonw).
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.free",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
                creationflags=flags)
            cells = [x.strip() for x in out.stdout.replace("%", " ").split(",")]
            nums = []
            for c in cells:
                num = "".join(ch for ch in c if ch.isdigit())
                nums.append(int(num) if num else None)
            util = nums[0] if len(nums) > 0 else None
            free = nums[1] if len(nums) > 1 else None
            return util, free
        except Exception:
            return None, None

    def is_busy(self):
        """Pause triggers: low free VRAM (a heavy game resident) or high
        GPU utilization. Resume needs both genuinely idle: VRAM back AND
        utilization at/below idle level. The band between holds last state,
        so borderline readings can't flap the poller."""
        util, free = self.gpu_status()
        if free is not None and free < self.min_free_mb:
            return True
        if util is not None and util >= self.max_gpu_util:
            return True
        if self.was_busy:
            if util is None and free is None:
                return False  # sensor dead: fail open, never stall forever
            if (free is not None and free >= self.min_free_mb
                    and util is not None and util <= self.idle_gpu_util):
                return False
            return True
        return False

    def unload_model(self):
        """Force the model out of VRAM. Returns True if acknowledged."""
        body = json.dumps({"model": self.model, "prompt": "ok",
                           "stream": False, "keep_alive": 0,
                           "options": {"num_predict": 1}}).encode()
        try:
            req = urllib.request.Request(
                self.ollama_url + "/api/generate", data=body,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30):
                pass
            return True
        except Exception:
            return False

    def check(self):
        """Returns (busy, just_changed). Callers log on just_changed."""
        busy = self.is_busy()
        changed = busy != self.was_busy
        self.was_busy = busy
        return busy, changed
