import unittest
from unittest.mock import patch
import pd_dspark_probe as probe


class CounterTests(unittest.TestCase):
    def test_two_decode_engines_are_added_once(self):
        def values(url):
            engine = '0' if url == 'd0' else '1'
            return {f'vllm:spec_decode_num_drafts_total{{engine="{engine}"}}': 10,
                    f'vllm:spec_decode_num_accepted_tokens_total{{engine="{engine}"}}': 5,
                    f'vllm:spec_decode_num_draft_tokens_total{{engine="{engine}"}}': 50,
                    f'vllm:spec_decode_num_accepted_tokens_per_pos_total{{engine="{engine}",position="0"}}': 4}
        with patch.object(probe, 'engine_metrics', values):
            result = probe.summarize(probe.metrics('d0,d1'), 5)
        self.assertEqual(result['draft_rounds'], 20)
        self.assertEqual(result['block_average_acceptance'], .1)
        self.assertEqual(result['per_position_acceptance']['0'], .4)

    def test_duplicate_engine_exposure_is_rejected(self):
        with patch.object(probe, 'engine_metrics', return_value={
                'vllm:spec_decode_num_drafts_total{engine="0"}': 1}):
            with self.assertRaises(RuntimeError):
                probe.metrics('d0,d1')

    def test_reset_is_rejected(self):
        with self.assertRaises(RuntimeError):
            probe.counter_delta({'drafts': 10}, {'drafts': 0})


if __name__ == '__main__':
    unittest.main()
