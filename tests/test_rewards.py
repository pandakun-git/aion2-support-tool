import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import update_rewards as u

class RewardsTests(unittest.TestCase):
 def test_ludra_drops_section_not_login_period(self):
  body='''Ludra event! Twitch Drops coming soon.\n## Login Rewards\n## Ludra Check-In\n■ Event Schedule\nPST: October 28, 2026 at 06:00 - November 10, 2026 at 23:59\n## Twitch Drops\n■ Event Schedule\nPST: November 4, 2026 at 06:00 - November 17, 2026 at 23:59\n## Other Event'''
  start,end=u.pick_drops_block(body)
  self.assertEqual(start,'2026-11-04T14:00:00Z')
  self.assertEqual(end,'2026-11-18T07:59:00Z')
 def test_japanese_date(self):
  body='■ Event Schedule 2026年11月4日(水) 23:00 ～ 11月18日(水) 16:59 JST'
  self.assertEqual(u.parse_drops_dates(body),('2026-11-04T14:00:00Z','2026-11-18T07:59:00Z'))
 def test_no_dates_no_drop(self):
  self.assertEqual(u.pick_drops_block('Twitch Drops is also happening. Stay tuned'),(None,None))
 def test_coupon_strict_source(self):
  items=u.discover_coupons('クーポンコード DAEVADRESSUP　有効期限 11月25日 メンテナンス開始前','https://x.com/AION2_JP','mirror')
  self.assertEqual(len(items),1)
  self.assertEqual(items[0]['code'],'DAEVADRESSUP')
  self.assertIsNone(items[0]['expires'])
  self.assertIn('時刻未確定',items[0]['expiry_note'])
 def test_steam_inbody_campaign(self):
  x={'gid':'1234567890','title':'Ludra Awakens on November 4th','url':'https://steamcommunity.com/games/3393110/announcements/detail/111','contents':'[h2]Login[/h2] Date 20th [h2]Twitch Drops[/h2] ■ Event Schedule PST: November 4, 2026 at 06:00 - November 17, 2026 at 23:59'}
  codes,drops=u.parse_steam_items([x]);self.assertEqual(len(drops),1);self.assertEqual(drops[0]['start'],'2026-11-04T14:00:00Z')
 def test_reject_other_game(self):
  x={'gid':'1','title':'Gaming','url':'https://example.net/other','contents':'[h2]Twitch Drops[/h2] PST: November 4, 2026 at 06:00 - November 17, 2026 at 23:59'}
  codes,drops=u.parse_steam_items([x]);self.assertEqual(len(drops),0)

if __name__=='__main__':unittest.main()

# Workflow-level regression checks use mock publisher responses, not live network.
class WorkflowTests(unittest.TestCase):
 def test_publish_snapshot_and_dedupe_seed_campaign(self):
  import tempfile
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as temp:
   snapshot=Path(temp)/'rewards.json'
   snapshot.write_text((Path(__file__).resolve().parents[1]/'data/rewards.json').read_text())
   article={'gid':'99','title':'Ludra event announcement','url':'https://steamcommunity.com/games/3393110/announcements/detail/99',
            'contents':'[h2]Twitch Drops[/h2]\n■ Event Schedule\nPST: November 4, 2026 at 06:00 - November 17, 2026 at 23:59'}
   fixed=u.dt.datetime(2026,11,15,6,0,tzinfo=u.UTC)
   with patch.object(u,'OUT',snapshot),patch.object(u,'now_utc',lambda:fixed),patch.object(u,'steam_news',return_value=([article],'Steam')),patch.object(u,'nc_global_board',side_effect=RuntimeError('blocked')),patch.object(u,'lounge_coupons',return_value=([], 'Lounge')),patch.object(u,'mirror_coupons',return_value=([], 'Mirror')):
    result=u.main()
   self.assertEqual(result,0)
   data=__import__('json').loads(snapshot.read_text())
   self.assertEqual(len(data['drops']),1)
   self.assertEqual(len(data['drops'][0]['rewards']),10)
   self.assertEqual(data['sources']['nc_global']['ok'],False)
   self.assertTrue(data['updated_at'])

 def test_total_failure_preserves_snapshot_timestamp(self):
  import tempfile
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as temp:
   snapshot=Path(temp)/'rewards.json'
   base=__import__('json').loads((Path(__file__).resolve().parents[1]/'data/rewards.json').read_text())
   base['updated_at']='2026-11-14T00:00:00Z'
   snapshot.write_text(__import__('json').dumps(base))
   with patch.object(u,'OUT',snapshot),patch.object(u,'steam_news',side_effect=RuntimeError('offline')),patch.object(u,'nc_global_board',side_effect=RuntimeError('offline')),patch.object(u,'lounge_coupons',side_effect=RuntimeError('offline')),patch.object(u,'mirror_coupons',side_effect=RuntimeError('offline')):
    result=u.main()
   self.assertEqual(result,2)
   data=__import__('json').loads(snapshot.read_text())
   self.assertEqual(data['updated_at'],'2026-11-14T00:00:00Z')
   self.assertEqual(len(data['coupons']),1)
