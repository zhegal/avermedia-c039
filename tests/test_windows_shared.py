"""Multiple consumers share immutable packets; consumers never own/stop USB."""
import os
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


@unittest.skipUnless(os.name == 'nt', 'Windows source binding')
class SharedSource(unittest.TestCase):
    def test_timed_subscription_survives_epoch_and_drains_admitted_prefix_on_stop(self):
        source=self.source(); got=[]; events=[]; started=threading.Event()
        session=source.session_factory(on_standard=lambda *args:started.set(),
            on_batch=lambda *args:got.append(args),allow_discontinuities=True,
            on_discontinuity=lambda *args:events.append(args),seconds=0)
        thread=threading.Thread(target=session.run); thread.start()
        self.assertTrue(started.wait(2))
        source._publish(('batch',4,b'old',((0,3,0),),1000000))
        source._publish(('end',1)); source._publish(('epoch',2))
        source._publish(('batch',4,b'new',((0,3,0),),3000000))
        session.stop()
        source._publish(('batch',4,b'after stop',((0,10,0),),4000000))
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual([row[1] for row in got],[b'old',b'new'])
        self.assertEqual([row[0] for row in events],['native_end','epoch'])
        self.assertFalse(source.closing.is_set())

    def source(self):
        from windows_preview import PreviewCapture
        source = PreviewCapture(None)
        source._publish(('profile', 1, 576, 25, 1))
        return source

    def test_two_consumers_receive_same_packet_objects_without_native_open(self):
        source = self.source(); got = [[], []]; errors = []
        subscriptions = [source.session_factory(on_standard=lambda *args: None,
            on_batch=lambda *values, index=index: got[index].append(values), seconds=0) for index in range(2)]

        def consume(subscription):
            try:
                subscription.run()
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=consume, args=(item,)) for item in subscriptions]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 1
        while len(source.subscribers) != 2 and time.monotonic() < deadline:
            time.sleep(.001)
        payload = bytes(2892); descriptors = ((0, 24, 0),)
        source._publish(('batch', 4, payload, descriptors, 1000000))
        source._publish(('end', 0))
        for thread in threads:
            thread.join(timeout=2); self.assertFalse(thread.is_alive())
        self.assertFalse(errors); self.assertEqual(got[0], got[1]); self.assertEqual(len(got[0]), 1)
        self.assertIs(got[0][0][1], payload)
        self.assertIsNone(source.native); self.assertFalse(source.closing.is_set())
        self.assertFalse(source.subscribers)

    def test_slow_consumer_failure_does_not_stop_source_or_other_consumer(self):
        source = self.source()
        slow = source.session_factory(on_standard=lambda *args: None, on_packet=lambda *args: None)
        source.subscribe(slow)
        for n in range(129):
            source._publish(('batch', 4, bytes(24), ((0,24,0),), 1000000+n*8000))
        self.assertIsNotNone(slow.failure)
        self.assertFalse(source.closing.is_set()); self.assertIsNone(source.native)
        self.assertGreater(source.state['preview_queue_resets'], 0)
        slow.close(); self.assertFalse(source.subscribers)

    def test_consumer_stop_and_source_epoch_never_close_logical_preview(self):
        source = self.source()
        subscription = source.session_factory(on_standard=lambda *args: None, on_packet=lambda *args: None)
        subscription.stop(); subscription.close()
        self.assertFalse(source.closing.is_set())
        from windows_shared import SharedSession
        item = SharedSession(source, on_standard=lambda *args: None, on_packet=lambda *args: None)
        item.offer(('epoch', 2))
        with self.assertRaisesRegex(Exception, 'epoch changed'):
            item.run()
        self.assertEqual(item.last_result, 1)
        self.assertFalse(source.closing.is_set()); self.assertFalse(source.subscribers)
