import {test,expect} from "@playwright/test";
import {mkdirSync} from "node:fs";
import path from "node:path";
const shots=path.resolve(process.cwd(),"../docs/screenshots");
mkdirSync(shots,{recursive:true});
test("thin Builder works end to end in Demo without external requests",async({page})=>{
 const external:string[]=[];
 await page.route("**/*",route=>{const url=new URL(route.request().url());if(!["localhost","127.0.0.1"].includes(url.hostname)){external.push(url.hostname);return route.abort();}return route.continue();});
 await page.setViewportSize({width:1440,height:1000});
 await page.goto("/");
 const demo=page.getByRole("button",{name:"Use Demo mode",exact:true});if(await demo.isVisible())await demo.click();
 await page.getByRole("button",{name:"Frankfurter",exact:true}).click();
 await expect(page.getByRole("heading",{name:"frankfurter",exact:true})).toBeVisible();
 await expect(page.getByRole("button",{name:"Download Python"})).toBeEnabled();
 await expect(page.locator(".monaco-editor")).toBeVisible();
 await page.getByRole("button",{name:"Backfill",exact:true}).click();
 await page.waitForResponse(r=>r.url().endsWith("/api/generate")&&r.request().postDataJSON()?.mode==="backfill"&&r.status()===200);
 const download=page.waitForEvent("download");await page.getByRole("button",{name:"Download Python"}).click();expect((await download).suggestedFilename()).toBe("frankfurter.py");
 await page.screenshot({animations:"disabled",path:path.join(shots,"builder-desktop.png"),fullPage:true});
 await page.getByRole("button",{name:"Research API",exact:true}).click();
 await expect(page.getByText(/tokens saved by cache/)).toBeVisible();
 await page.keyboard.press("Control+k");await expect(page.getByRole("dialog")).toBeVisible();await page.getByLabel("Search commands").fill("Toggle theme");await page.getByRole("button",{name:"Toggle theme",exact:true}).last().click();
 await expect(page.locator("html")).toHaveAttribute("data-theme","light");await page.getByRole("button",{name:"Toggle theme",exact:true}).first().click();
 expect(external).toEqual([]);
});
for(const width of [1440,820])test(`main views and onboarding at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:1100});await page.goto("/");
 const demo=page.getByRole("button",{name:"Use Demo mode",exact:true});if(await demo.isVisible())await demo.click();
 await page.getByRole("button",{name:"CoinGecko",exact:true}).click();
 await expect(page.getByRole("heading",{name:"coingecko",exact:true})).toBeVisible();
 await expect(page.getByRole("button",{name:"Download Python"})).toBeEnabled();
 await expect(page.locator(".monaco-editor")).toBeVisible();
 await page.screenshot({animations:"disabled",path:path.join(shots,`builder-${width===820?"tablet":"coingecko"}.png`),fullPage:true});
 for(const tab of ["Converter","Explain","Office"]){await page.getByRole("tab",{name:tab,exact:true}).click();await expect(page.getByRole("heading",{name:tab==="Converter"?"SQL in. DataFrames out.":tab==="Explain"?"Understand the code behind it.":"A live view of real work.",exact:true})).toBeVisible();if(tab==="Office")await page.screenshot({animations:"disabled",path:path.join(shots,`${tab.toLowerCase()}-${width===820?"tablet":"desktop"}.png`),fullPage:true});}
 await page.getByRole("button",{name:"Settings",exact:true}).click();await expect(page.getByRole("dialog")).toBeVisible();
 // Never check the actual Codex installation/login during development.
 await page.route("**/api/providers/codex/status",route=>route.fulfill({json:{logged_in:false,available:false,code:"cli_missing",message:"Install Codex and run codex login on the host."}}));
 await page.getByLabel("Provider",{exact:true}).selectOption("codex_cli");await expect(page.getByText(/Host mode.*uses Codex quota/)).toBeVisible();
 await page.screenshot({animations:"disabled",path:path.join(shots,`settings-${width===820?"tablet":"desktop"}.png`),fullPage:true});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
});
