import {test,expect} from "@playwright/test";
import path from "node:path";
for(const width of [1440,820])test(`Converter and Explain work offline at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:1100});await page.goto("/");
 const demo=page.getByRole("button",{name:"Use Demo mode",exact:true});if(await demo.isVisible())await demo.click();
 await page.getByRole("tab",{name:"Converter",exact:true}).click();
 await expect(page.getByRole("heading",{name:"SQL in. DataFrames out."})).toBeVisible();
 await page.getByRole("button",{name:"Convert SQL",exact:true}).click();
 await expect(page.getByText("AST compiled",{exact:true}).or(page.getByText("Cached result",{exact:true}))).toBeVisible();
 await expect(page.locator(".monaco-editor")).toHaveCount(3);
 await page.getByText("Verify with sample data (zero LLM calls)",{exact:true}).click();await page.getByRole("button",{name:"Verify result",exact:true}).click();await expect(page.getByText(/PASS: pandas matches DuckDB/)).toBeVisible();
 await page.screenshot({path:path.resolve(`../docs/screenshots/converter-${width===820?"tablet":"desktop"}.png`),fullPage:true,animations:"disabled"});
 await page.getByRole("tab",{name:"Explain",exact:true}).click();await page.getByRole("button",{name:"Explain code",exact:true}).click();await expect(page.getByRole("heading",{name:"Menyalin semua lajur dan baris daripada source."})).toBeVisible();
 await page.screenshot({path:path.resolve(`../docs/screenshots/explain-${width===820?"tablet":"desktop"}.png`),fullPage:true,animations:"disabled"});
 await page.getByRole("button",{name:"Convert to pandas",exact:true}).click();await expect(page.getByRole("heading",{name:"SQL in. DataFrames out."})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});
