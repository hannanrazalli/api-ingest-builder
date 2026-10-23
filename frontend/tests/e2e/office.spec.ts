import {test,expect} from "@playwright/test";
import path from "node:path";
for(const width of [1440,820])test(`Office replays every zone and mini mode at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:1100});await page.goto("/");const demo=page.getByRole("button",{name:"Use Demo mode",exact:true});if(await demo.isVisible())await demo.click();
 await page.getByRole("tab",{name:"Office",exact:true}).click();await page.getByRole("button",{name:"Replay demo",exact:true}).click();
 await expect(page.locator('[data-zone][data-visited="true"]')).toHaveCount(11,{timeout:20000});
 await page.screenshot({path:path.resolve(`../docs/screenshots/office-overview-${width===820?"tablet":"desktop"}.png`),fullPage:true,animations:"disabled"});
 await page.getByRole("button",{name:/Workshop success/}).click();await expect(page.getByRole("heading",{name:"repair",exact:true})).toBeVisible();
 await page.getByLabel("Filter agent activity").selectOption("repair");await expect(page.locator(".activity-log li")).not.toHaveCount(0);
 await page.screenshot({path:path.resolve(`../docs/screenshots/office-${width===820?"tablet":"desktop"}.png`),fullPage:true,animations:"disabled"});
 await page.getByRole("button",{name:"Stop following agent"}).click();await page.getByRole("button",{name:"Enable mini mode",exact:true}).click();await page.getByRole("tab",{name:"Builder",exact:true}).click();await expect(page.getByRole("region",{name:"Mini Office",exact:true})).toBeVisible();
 await page.getByRole("button",{name:"Close mini Office"}).click();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});
