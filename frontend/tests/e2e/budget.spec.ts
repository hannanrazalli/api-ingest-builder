import {test,expect} from "@playwright/test";
import path from "node:path";
for(const width of [1440,820])test(`budget review persists and declines without provider calls at ${width}px`,async({page,request})=>{
 await request.put("/api/settings",{data:{provider:"openai",api_key:"budget-test-placeholder",model_fast:"fixture-fast",max_llm_calls:0}});
 try{
  await page.setViewportSize({width,height:1100});await page.goto("/");
  await page.getByRole("tab",{name:"Explain",exact:true}).click();
  const editor=page.getByRole("textbox",{name:"Code input",exact:true});await editor.focus();await page.keyboard.press("Control+a");await editor.pressSequentially(`value = ${width} # budget review`,{delay:30});
  const blocked=page.waitForResponse(r=>r.url().endsWith("/api/explain"));
  await page.getByRole("button",{name:"Explain code",exact:true}).click();const response=await blocked;expect(response.status()).toBe(409);const job=(await response.json()).job;
  const review=page.getByRole("region",{name:"Job budget review"});await expect(review).toBeVisible();
  await expect(page.getByLabel("Total LLM calls",{exact:true})).toHaveValue("1");
  expect(job.calls).toBe(0);
  await page.screenshot({path:path.resolve(`../docs/screenshots/budget-${width}.png`),fullPage:true,animations:"disabled"});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.reload();await page.locator(".history-item").filter({has:page.locator(".status-dot.waiting")}).first().click();await expect(review).toBeVisible();
  await page.getByRole("button",{name:"Decline & stop",exact:true}).click();await expect(review).toHaveCount(0);
  const stopped=await (await request.get(`/api/jobs/${job.id}`)).json();expect(stopped.status).toBe("error");expect(stopped.calls).toBe(0);
 }finally{await request.put("/api/settings",{data:{api_key:"",model_fast:"",max_llm_calls:3}});await request.post("/api/onboarding/demo");}
});
test("approved response renders in Explain and approval stays scoped to its job",async({page,request})=>{
 await request.put("/api/settings",{data:{provider:"openai",api_key:"budget-test-placeholder",model_fast:"fixture-fast",max_llm_calls:0}});
 try{
  await page.goto("/");await page.getByRole("tab",{name:"Explain",exact:true}).click();
  await page.getByRole("textbox",{name:"Code input",exact:true}).focus();await page.keyboard.press("Control+a");await page.getByRole("textbox",{name:"Code input",exact:true}).pressSequentially("value = 99 # approval rendering",{delay:30});
  const blocked=page.waitForResponse(r=>r.url().endsWith("/api/explain"));await page.getByRole("button",{name:"Explain code",exact:true}).click();const response=await blocked;expect(response.status()).toBe(409);const job=(await response.json()).job;
  // Provider execution is covered by backend transport fixtures. This verifies response rendering without a live inference call.
  await page.route(`**/api/jobs/${job.id}/budget`,async route=>{expect(route.request().postDataJSON().max_llm_calls).toBe(1);await route.fulfill({json:{operation:"explain",job:{...job,status:"success",calls:1},result:{job:{...job,status:"success",calls:1},explanation:{language:"Malay",summary:"Nilai ditetapkan kepada 99.",steps:[],concepts:[]},detected:"Python",sql:null,cache_hit:false}}});});
  await page.getByRole("button",{name:"Approve & retry job",exact:true}).click();await expect(page.getByRole("heading",{name:"Nilai ditetapkan kepada 99."})).toBeVisible();
  expect((await (await request.get("/api/settings")).json()).max_llm_calls).toBe(0);
  await request.post(`/api/jobs/${job.id}/budget`,{data:{approve:false}});
 }finally{await request.put("/api/settings",{data:{api_key:"",model_fast:"",max_llm_calls:3}});await request.post("/api/onboarding/demo");}
});
