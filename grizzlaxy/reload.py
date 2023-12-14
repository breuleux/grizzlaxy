import asyncio
import logging
import os
import sys
from asyncio import Future
from uuid import uuid4

from sse_starlette.sse import EventSourceResponse
from starlette.routing import Route
from watchdog.observers import Observer

logger = logging.getLogger("starbear")


class Looper:
    def __init__(self, reloader):
        self.future = None
        self.reloader = reloader
        self.reloader.activity.append(self.handle)

    def handle(self):
        if self.future and not self.future.done():
            self.future.set_result(True)

    async def __aiter__(self):
        try:
            while True:
                self.future = Future()
                await self.future
                await asyncio.sleep(0.05)
                yield True
        except asyncio.CancelledError:
            self.reloader.activity.remove(self.handle)


async def autofire():
    yield True


class InertReloader:
    def __init__(self, gz):
        self.gz = gz
        self.uuid = uuid4().hex
        self.activity = []
        self.has_fired = False

    def prep(self):
        pass

    def code_watch(self, watch, module):
        pass

    def browser_side_code(self):
        return None

    def inject_routes(self, routes):
        pass


class BaseReloader(InertReloader):
    def browser_side_code(self):
        return f"""
        let src = new EventSource("/!!{self.uuid}/events");
        function reboot() {{
            fetch("/!!{self.uuid}/reboot");
            setTimeout(() => window.location.reload(), 500);
        }}
        $$BEAR.tabs.addButton("⟳", reboot);
        """

    def code_watch(self, watch, module):
        self.obs = Observer()
        self.obs.schedule(self, watch, recursive=True)
        self.obs.start()

    async def route_events(self, request):
        return EventSourceResponse(Looper(self))

    async def reboot(self, request):
        logger.info("Rebooting the server...")
        os.execv(sys.argv[0], sys.argv)

    def inject_routes(self, routes):
        routes.insert(0, Route(f"/!!{self.uuid}/events", self.route_events))
        routes.insert(0, Route(f"/!!{self.uuid}/reboot", self.reboot))

    def is_watched(self, pth):
        return not ("__pycache__" in pth or pth.endswith(".pyc"))

    def fire(self):
        self.has_fired = True
        for listener in self.activity:
            listener()

    def dispatch(self, event):
        if self.is_watched(event.src_path):
            self.fire()


class JuriggedReloader(BaseReloader):
    def __init__(self, gz):
        from jurigged.codetools import CodeFileOperation
        from jurigged.register import registry

        super().__init__(gz)
        self.registry = registry
        self.op = CodeFileOperation

    def prep(self):
        # Sometimes has to be done before importing the module to watch in order
        # to properly collect function data
        import codefind  # noqa: F401

    def code_watch(self, watch, module):
        import jurigged

        super().code_watch(watch, module)
        jurigged.watch(str(watch))
        self.activity.append(self.gz.set_routes)
        self.registry.activity.register(self.handle_jurigged)

    def browser_side_code(self):
        code = super().browser_side_code()
        return (
            code
            + """
        src.onmessage = e => {
            window.location.reload();
        };
        """
        )

    def handle_jurigged(self, event):
        if isinstance(event, self.op):
            self.fire()

    def is_watched(self, pth):
        return super().is_watched(pth) and not pth.endswith(".py")


class FullReloader(BaseReloader):
    def __init__(self, gz):
        super().__init__(gz)
        self.donezo = False

    async def route_events(self, request):
        if self.has_fired:
            return EventSourceResponse(autofire())
        else:
            return EventSourceResponse(Looper(self))

    def browser_side_code(self):
        code = super().browser_side_code()
        return (
            code
            + """
        src.onmessage = reboot;
        """
        )
