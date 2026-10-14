#!/usr/bin/env python3
"""Actual Playwright UI smoke: desktop/mobile, filters, drawer, history, axe.
Run against a local app after a completed measured job; no scans are submitted.
"""
import argparse
import asyncio
import json
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

parser=argparse.ArgumentParser()
parser.add_argument("--app",default="http://127.0.0.1:8080")
parser.add_argument("--job",required=True)
parser.add_argument("--output",type=Path,default=Path("docs/screenshots"))
args=parser.parse_args()
args.output.mkdir(parents=True,exist_ok=True)
ROOT=Path(__file__).resolve().parents[1]

async def main():
    result={"app":args.app,"job":args.job,"checks":{},"console_errors":[],"accessibility":{}}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        page=await browser.new_page(viewport={"width":1440,"height":1100},device_scale_factor=1)
        page.on("pageerror",lambda error:result["console_errors"].append(str(error)))
        async def audit(name):
            await page.add_script_tag(path=str(ROOT/"tools/node_modules/axe-core/axe.min.js"))
            data=await page.evaluate("async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})")
            result["accessibility"][name]=[{"id":v['id'],"impact":v['impact'],"description":v['description'],"nodes":[{'target':n['target'],'summary':n['failureSummary']} for n in v['nodes'][:12]]} for v in data['violations']]
        await page.goto(args.app,wait_until="networkidle")
        await page.get_by_role('heading',name='Start a website test').wait_for()
        assert await page.get_by_role('checkbox').count()==4
        assert all([await box.is_checked() for box in await page.get_by_role('checkbox').all()])
        await page.get_by_label('Website URL',exact=True).fill('https://example.com/')
        await page.get_by_text('Security & load will be refused',exact=True).wait_for()
        result['checks']['url_only_home_and_authorization_warning']=True
        await page.get_by_label('Website URL',exact=True).fill('')
        await page.screenshot(path=str(args.output/'home-desktop.png'),full_page=True,animations='disabled')
        await audit('home-desktop')
        await page.goto(f'{args.app}/reports/{args.job}',wait_until='networkidle')
        await page.get_by_role('heading',name='Website health report',exact=True).wait_for()
        await page.screenshot(path=str(args.output/'report-desktop.png'),full_page=True,animations='disabled')
        await audit('report-desktop')
        await page.locator('.report-tabs button').filter(has_text='All findings').click()
        await page.get_by_role('combobox',name='Filter by pillar').select_option('security')
        await page.get_by_role('combobox',name='Filter by severity').select_option('Medium')
        rows=page.locator('.issues-table tbody tr')
        assert await rows.count()>0
        texts=[await row.inner_text() for row in await rows.all()]
        assert all('Security' in text and 'Medium' in text for text in texts)
        result['checks']['pillar_and_severity_filters']=True
        await page.locator('.issue-title').first.click()
        await page.get_by_role('dialog').wait_for()
        await page.get_by_text('Suggested fix',exact=True).wait_for()
        await page.screenshot(path=str(args.output/'issue-evidence.png'),full_page=False,animations='disabled')
        await audit('issue-drawer')
        await page.keyboard.press('Escape')
        assert await page.get_by_role('dialog').count()==0
        result['checks']['evidence_drawer_and_escape']=True
        await page.goto(args.app+'/history',wait_until='networkidle')
        assert await page.locator('.history-table tbody tr').count()>0
        await page.screenshot(path=str(args.output/'history-desktop.png'),full_page=True,animations='disabled')
        await audit('history-desktop')
        result['checks']['durable_history']=True
        await page.set_viewport_size({'width':390,'height':844})
        await page.goto(args.app,wait_until='networkidle')
        await page.screenshot(path=str(args.output/'home-mobile.png'),full_page=True,animations='disabled')
        await audit('home-mobile')
        assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+1')
        await page.goto(f'{args.app}/reports/{args.job}',wait_until='networkidle')
        await page.screenshot(path=str(args.output/'report-mobile.png'),full_page=True,animations='disabled')
        assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+1')
        result['checks']['mobile_no_page_overflow']=True
        await browser.close()
    with httpx.Client(base_url=args.app,timeout=90) as client:
        for format in ['html','pdf','json']:
            response=client.get(f'/api/reports/{args.job}/export/{format}')
            response.raise_for_status()
            if format=='pdf':assert response.content.startswith(b'%PDF')
            if format=='html':assert b'data:image/png;base64,' in response.content
            if format=='json':assert response.json()['id']==args.job
            result['checks'][format+'_export']=True
    (args.output/'ui-validation.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

asyncio.run(main())
