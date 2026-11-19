"""Exercise the actual composition path, not just its candidate enrichment helpers."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.agents import composer
from app.agents.context import PlanningContext
from app.services.experiences import prompt as experience_prompt


class ComposerGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def run_composition(self, lean, days):
        preferences = experience_prompt({'mode': 'balanced', 'interests': ['markets']})
        ctx = PlanningContext(location='Düsseldorf', days=days, preferences=preferences)
        calls = []
        class Router:
            primary_model = 'test-model'
            async def generate_json_stream(self, **kwargs):
                calls.append(kwargs)
                day = int(kwargs['step'].removeprefix('compose_day'))
                yield 'result', SimpleNamespace(content=json.dumps({'day': day, 'title': '城市生活', 'activities': [{'name': f'Park {day}', 'time': '10:00-11:00', 'description': '公园散步'}], 'meals': []}))
        for day in range(1, days + 1):
            ctx.attractions_by_day[day] = [{'name': f'Park {day}', 'lat': 51.2 + day * .01, 'lng': 6.77, 'primary_type': 'park', 'formatted_address': 'Düsseldorf'}]
        with patch.object(composer, '_use_lean', return_value=lean), patch.object(composer, 'get_llm_router', return_value=Router()), patch.object(composer.ctx_mod, 'emit', new=AsyncMock()) as emit:
            result = await composer.compose(ctx)
        self.assertEqual(len(result['itinerary']), days)
        self.assertEqual(len(calls), days)
        self.assertFalse(ctx.fallback_days, 'Valid model output must not silently fall back')
        for call in calls:
            self.assertIsInstance(call['user_prompt'], str)
            self.assertIn('Düsseldorf', call['user_prompt'])
            self.assertIn('[experience:balanced|markets]', call['system_prompt'])
            self.assertIn('候选中的体验时长和季节确认条件必须保留', call['system_prompt'])
        emitted = [a.args[0]['day'] for a in emit.await_args_list if a.args[0].get('type') == 'day']
        self.assertEqual(sorted(emitted), list(range(1, days + 1)))

    async def test_lean_single_day(self):
        await self.run_composition(True, 1)

    async def test_standard_single_day(self):
        await self.run_composition(False, 1)

    async def test_lean_multiple_days(self):
        await self.run_composition(True, 3)

    async def test_standard_multiple_days(self):
        await self.run_composition(False, 3)
