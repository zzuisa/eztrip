import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.services import xiaohongshu_service as svc
from app.tools import catalog
from app.agents.subagents import _summarize_notes
from app.api.routes import xiaohongshu as api
from app.services.guest_guard import require_owner


def result(data=None,text=None,error=False,structured=None):
    return SimpleNamespace(content=[SimpleNamespace(type='text',text=text if text is not None else json.dumps(data))],isError=error,structuredContent=structured)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.settings=SimpleNamespace(enable_xiaohongshu_mcp=True,xiaohongshu_mcp_base_url='http://litellm:4000/litellm/xiaohongshu/mcp',xiaohongshu_mcp_timeout_seconds=90,xiaohongshu_mcp_api_key='private-test-key',xiaohongshu_mcp_server='xiaohongshu')
        self.config=patch.object(svc,'get_settings',return_value=self.settings);self.config.start();self.service=svc.XiaohongshuService()
    def tearDown(self):self.config.stop()
    def test_nested_note_cards_are_consumed_by_existing_planning_agent(self):
        upstream={'feeds':[{'id':'note1','xsecToken':'private-feed-token','noteCard':{'displayTitle':'杜塞周末市集','desc':'当地美食与散步'}}]}
        with patch.object(self.service,'_invoke',new=AsyncMock(return_value=result(upstream))) as call:
            response=self.service.search_feeds('杜塞 周末',{'sort_by':'最新','unknown':'discard'})
        self.assertEqual(response['data']['count'],1);self.assertIn('杜塞周末市集',_summarize_notes(response));self.assertEqual(response['data']['feeds'][0]['xsec_token'],'private-feed-token');self.assertEqual(call.await_args.args,('search_feeds',{'keyword':'杜塞 周末','filters':{'sort_by':'最新'}}))
    def test_detail_uses_mcp_flat_parameters_instead_of_old_rest_comment_config(self):
        with patch.object(self.service,'_invoke',new=AsyncMock(return_value=result({'feed_id':'n','note':{'title':'A'}}))) as call:
            self.service.get_feed_detail('n','token',load_all_comments=True,limit=15,reply_limit=4,click_more_replies=True)
        tool,args=call.await_args.args;self.assertEqual(tool,'get_feed_detail');self.assertEqual(args['limit'],15);self.assertEqual(args['reply_limit'],4);self.assertNotIn('comment_config',args)
    def test_detail_preserves_feed_id_and_nested_data_for_existing_api_consumers(self):
        upstream={'feed_id':'n','data':{'note':{'title':'A'},'comments':{}}}
        with patch.object(self.service,'_invoke',new=AsyncMock(return_value=result(upstream))):
            response=self.service.get_feed_detail('n','token')
        self.assertEqual(response['data']['feed_id'],'n');self.assertEqual(response['data']['data']['note']['title'],'A')
    def test_unlogged_and_verification_errors_are_safe_and_distinguishable(self):
        for text,code in [('LOGIN_REQUIRED token=private-test-key','login_required'),('SECURITY_VERIFICATION_REQUIRED','verification_required')]:
            with patch.object(self.service,'_invoke',new=AsyncMock(return_value=result(text=text,error=True))):
                with self.assertRaises(svc.XiaohongshuError) as raised:self.service.search_feeds('旅行')
            self.assertEqual(raised.exception.code,code);self.assertNotIn('private-test-key',str(raised.exception))
    def test_transport_errors_cannot_expose_credentials_or_note_tokens(self):
        with patch.object(self.service,'_invoke',new=AsyncMock(side_effect=RuntimeError('Authorization Bearer private-test-key xsec_token=secret'))):
            with self.assertRaises(svc.XiaohongshuError) as raised:self.service.search_feeds('旅行')
        self.assertEqual(raised.exception.code,'connection_failed');self.assertNotIn('secret',str(raised.exception));self.assertNotIn('private-test-key',str(raised.exception))
    def test_model_cannot_invoke_account_writes(self):
        with patch.object(self.service,'_invoke',new=AsyncMock()) as call:
            for tool in ['publish_content','delete_cookies','like_feed','execute_account_cleanup']:
                with self.assertRaises(svc.XiaohongshuError):self.service._call_tool(tool,{})
            call.assert_not_awaited()
    def test_empty_search_is_valid_but_missing_feed_list_is_not(self):
        with patch.object(self.service,'_invoke',new=AsyncMock(return_value=result({'feeds':[]}))):self.assertEqual(self.service.search_feeds('旅行')['data']['count'],0)
        for response in [result(text='登录失败'),result({'success':False}),result({'unexpected':'data'})]:
            with patch.object(self.service,'_invoke',new=AsyncMock(return_value=response)):
                with self.assertRaises(svc.XiaohongshuError):self.service.search_feeds('旅行')
    def test_explicit_gateway_credentials_required_no_fallback_to_model_key(self):
        self.service._api_key=''
        with self.assertRaises(svc.XiaohongshuError):self.service.search_feeds('旅行')
    def test_upstream_status_is_never_inferred_from_cookie_file(self):
        for text,expected in [('✅ 已登录\n站点: rednote',True),('❌ 未登录\n检查站点: rednote',False)]:
            with patch.object(self.service,'_invoke',new=AsyncMock(return_value=result(text=text))):self.assertEqual(self.service.check_login_status()['is_logged_in'],expected)
    def test_existing_tool_bus_degrades_without_interrupting_planning(self):
        with patch.object(catalog,'get_settings',return_value=self.settings),patch.object(catalog,'get_xiaohongshu_service',return_value=self.service),patch.object(self.service,'_invoke',new=AsyncMock(return_value=result(text='LOGIN_REQUIRED',error=True))):
            response=catalog._xhs_search_feeds('旅行');self.assertFalse(response['available']);self.assertEqual(response['feeds'],[])
    def test_owner_api_preserves_access_control_and_reports_real_login_status(self):
        app=FastAPI();app.include_router(api.router,prefix='/api');client=TestClient(app)
        with patch.object(api,'get_settings',return_value=self.settings),patch.object(api,'get_xiaohongshu_service',return_value=self.service):
            self.assertIn(client.get('/api/xhs/health').status_code,(401,403))
            app.dependency_overrides[require_owner]=lambda:None
            with patch.object(self.service,'check_login_status',return_value={'is_logged_in':True}):
                response=client.get('/api/xhs/health');self.assertEqual(response.status_code,200);self.assertEqual(response.json()['status'],'ready');self.assertNotIn('base_url',response.json())
            with patch.object(self.service,'search_feeds',return_value={'success':True,'data':{'feeds':[],'count':0}}):self.assertTrue(client.post('/api/xhs/search',json={'keyword':'旅行'}).json()['success'])


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_handshake_authentication_and_namespacing(self):
        settings=SimpleNamespace(xiaohongshu_mcp_base_url='http://litellm:4000/litellm/xiaohongshu/mcp',xiaohongshu_mcp_timeout_seconds=90,xiaohongshu_mcp_api_key='private-test-key',xiaohongshu_mcp_server='xiaohongshu')
        from contextlib import asynccontextmanager
        session=SimpleNamespace(initialize=AsyncMock(),call_tool=AsyncMock(return_value=result({'feeds':[]})))
        @asynccontextmanager
        async def transport(*args,**kwargs):yield ('read','write',None)
        @asynccontextmanager
        async def client(*args):yield session
        with patch.object(svc,'get_settings',return_value=settings),patch.object(svc,'streamablehttp_client',side_effect=transport) as connect,patch.object(svc,'ClientSession',side_effect=client):
            await svc.XiaohongshuService()._invoke('search_feeds',{'keyword':'旅行'})
        session.initialize.assert_awaited_once();session.call_tool.assert_awaited_once_with('xiaohongshu-search_feeds',{'keyword':'旅行'});self.assertEqual(connect.call_args.kwargs['headers']['Authorization'],'Bearer private-test-key');self.assertEqual(connect.call_args.kwargs['timeout'],90)
