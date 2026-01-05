import os
import asyncio
import re
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from playwright.async_api import async_playwright

# Configuration
APP_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = APP_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
CHROME_PROFILE = str(APP_DIR / "chrome_profile")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request Model
class GenerateRequest(BaseModel):
    title_prompt: str
    desc_prompt: str
    bullet_prompt: str
    title_data: str = ""
    desc_data: str = ""
    bullet_data: str = ""
    title_count: int = 5
    desc_count: int = 5
    bullet_count: int = 8
    title_length: int = 100
    desc_length: int = 300
    bullet_length: int = 80


@app.get("/")
async def serve_dashboard():
    """Serve the frontend HTML"""
    html_file = APP_DIR / "dashboard.html"
    if html_file.exists():
        return FileResponse(html_file)
    return JSONResponse({"error": "Dashboard not found"}, status_code=404)


@app.post("/generate")
async def generate_content(request: GenerateRequest):
    """Generate content using Gemini via Playwright"""
    
    print("\n" + "="*70)
    print("🎯 NEW CONTENT GENERATION REQUEST")
    print("="*70)
    print(f"📊 Requesting: {request.title_count} titles, {request.desc_count} descriptions, {request.bullet_count} bullets")
    print(f"📏 Lengths: Title={request.title_length}, Desc={request.desc_length}, Bullet={request.bullet_length}")
    
    try:
        result = await generate_via_gemini(request)
        
        if result["success"]:
            print(f"\n✅ Generation complete!")
            print(f"   Generated: {len(result['titles'])} titles, {len(result['descriptions'])} descriptions, {len(result['bullets'])} bullets")
            return JSONResponse(result)
        else:
            print("\n❌ Generation failed")
            return JSONResponse(result, status_code=500)
            
    except Exception as e:
        print(f"\n❌ Server error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e),
            "titles": [],
            "descriptions": [],
            "bullets": []
        }, status_code=500)


async def generate_via_gemini(request: GenerateRequest) -> dict:
    """Launch browser and generate content from Gemini"""
    
    async with async_playwright() as p:
        print("🚀 Launching Chrome...")
        os.makedirs(CHROME_PROFILE, exist_ok=True)
        
        try:
            context = await p.chromium.launch_persistent_context(
                CHROME_PROFILE,
                headless=False,
                channel="chrome",
                args=["--disable-blink-features=AutomationControlled"],
                slow_mo=50
            )
        except:
            context = await p.chromium.launch_persistent_context(
                CHROME_PROFILE,
                headless=False,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                slow_mo=50
            )

        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        titles = []
        descriptions = []
        bullets = []

        try:
            # Navigate to Gemini
            print("📱 Navigating to Gemini...")
            await page.goto("https://gemini.google.com/app", timeout=120000, wait_until="domcontentloaded")
            await asyncio.sleep(3)
            
            # Check if logged in
            chat_check = await page.query_selector("div[contenteditable='true']")
            if chat_check:
                print("✅ Already signed in!")
                await asyncio.sleep(2)
            else:
                print("⚠️  Sign in required - waiting 90 seconds...")
                await asyncio.sleep(90)
            
            await page.wait_for_selector("div[contenteditable='true']", timeout=60000)

            # Build the comprehensive prompt
            prompt = build_generation_prompt(request)
            
            # Save prompt for debugging
            debug_file = OUTPUT_DIR / "last_prompt.txt"
            with open(debug_file, "w", encoding="utf-8") as f:
                f.write(prompt)
            print(f"💾 Saved prompt to: {debug_file}")
            
            # Send prompt to Gemini
            print("💬 Sending prompt to Gemini...")
            await send_prompt_to_gemini(page, prompt)
            
            # Wait for response
            print("⏳ Waiting for Gemini response...")
            await asyncio.sleep(35)  # Give time for generation
            
            # Extract response
            response_text = await extract_gemini_response(page)
            
            if not response_text:
                raise Exception("Empty response from Gemini")
            
            print(f"📝 Response length: {len(response_text)} characters")
            
            # Save response for debugging
            debug_file = OUTPUT_DIR / "last_response.txt"
            with open(debug_file, "w", encoding="utf-8") as f:
                f.write(response_text)
            print(f"💾 Saved response to: {debug_file}")
            
            # Parse response
            titles, descriptions, bullets = parse_gemini_response(
                response_text,
                request.title_count,
                request.desc_count,
                request.bullet_count
            )
            
            # Fill missing items with defaults
            while len(titles) < request.title_count:
                titles.append(f"Generated Title {len(titles) + 1}")
            while len(descriptions) < request.desc_count:
                descriptions.append(f"Generated Description {len(descriptions) + 1}")
            while len(bullets) < request.bullet_count:
                bullets.append(f"Generated Bullet Point {len(bullets) + 1}")

        except Exception as e:
            print(f"❌ Generation error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await context.close()

        return {
            "success": len(titles) > 0 or len(descriptions) > 0 or len(bullets) > 0,
            "titles": titles[:request.title_count],
            "descriptions": descriptions[:request.desc_count],
            "bullets": bullets[:request.bullet_count]
        }


def build_generation_prompt(request: GenerateRequest) -> str:
    """Build comprehensive prompt for Gemini"""
    
    prompt = f"""You are an expert e-commerce content writer. Generate product content based on the following instructions.

**PROMPTS (How to write):**
- Title Prompt: {request.title_prompt}
- Description Prompt: {request.desc_prompt}
- Bullet Prompt: {request.bullet_prompt}

**REFERENCE DATA (What to base content on):**
"""
    
    if request.title_data:
        prompt += f"\nTitle Reference Data:\n{request.title_data}\n"
    
    if request.desc_data:
        prompt += f"\nDescription Reference Data:\n{request.desc_data}\n"
    
    if request.bullet_data:
        prompt += f"\nBullet Reference Data:\n{request.bullet_data}\n"
    
    prompt += f"""

**GENERATION REQUIREMENTS:**
1. Generate EXACTLY {request.title_count} titles, {request.desc_count} descriptions, {request.bullet_count} bullets
2. Each title should be approximately {request.title_length} characters
3. Each description should be approximately {request.desc_length} characters
4. Each bullet should be approximately {request.bullet_length} characters
5. Use the prompts to guide your writing style
6. Use the reference data to understand what type of content to create

**CRITICAL OUTPUT FORMAT - FOLLOW EXACTLY:**

TITLES:
Title 1: [Write actual title here]
Title 2: [Write actual title here]
Title 3: [Write actual title here]
...

DESCRIPTIONS:
Description 1: [Write actual description here]
Description 2: [Write actual description here]
...

BULLETS:
Bullet 1: [Write actual bullet here]
Bullet 2: [Write actual bullet here]
...

**IMPORTANT RULES:**
- Start IMMEDIATELY with "TITLES:" followed by numbered items
- Each item must be on its OWN LINE
- Use format "Title 1:", "Description 2:", "Bullet 3:" for EVERY item
- Write REAL content - NO placeholders like "[write content here]"
- Follow the character length guidelines closely
- Base content on the reference data provided

Now generate the content. Start with "TITLES:" immediately."""
    
    return prompt


async def send_prompt_to_gemini(page, prompt: str):
    """Send prompt to Gemini chat"""
    try:
        chat_box = await page.query_selector("div[contenteditable='true']")
        await chat_box.click()
        await asyncio.sleep(0.5)
        
        # Use JavaScript to set text (faster for long prompts)
        await page.evaluate(f"""
            (promptText) => {{
                const chatBox = document.querySelector('div[contenteditable="true"]');
                if (chatBox) {{
                    chatBox.textContent = promptText;
                    chatBox.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    const range = document.createRange();
                    const sel = window.getSelection();
                    range.selectNodeContents(chatBox);
                    range.collapse(false);
                    sel.removeAllRanges();
                    sel.addRange(range);
                }}
            }}
        """, prompt)
        
        await asyncio.sleep(1)
        await page.keyboard.press("Enter")
        print("✅ Prompt sent!")
        
    except Exception as e:
        print(f"❌ Failed to send prompt: {e}")
        raise


async def extract_gemini_response(page) -> str:
    """Extract Gemini's text response"""
    try:
        print("⏳ Waiting for response to appear...")
        await asyncio.sleep(8)
        
        # Try multiple selectors
        response_selectors = [
            "[data-message-author-role='model']",
            "model-response",
            "[class*='model-response']"
        ]
        
        response_elem = None
        for i in range(120):  # Wait up to 2 minutes
            for selector in response_selectors:
                try:
                    response_elem = await page.query_selector(selector)
                    if response_elem:
                        break
                except:
                    pass
            
            if response_elem:
                break
            
            # Check if response started appearing in page text
            if i > 10:
                has_response = await page.evaluate("""
                    () => {
                        const allText = document.body.innerText;
                        return allText.includes('TITLES:') || allText.includes('Title 1:');
                    }
                """)
                
                if has_response:
                    print("✅ Response detected in page")
                    break
            
            await asyncio.sleep(1)
            if i % 15 == 0 and i > 0:
                print(f"   Still waiting... {i}s")
        
        # Wait for completion
        print("⏳ Waiting for generation to complete...")
        await asyncio.sleep(5)
        
        for i in range(60):
            try:
                stop_button = await page.query_selector("button[aria-label*='Stop']")
                if not stop_button:
                    print("✅ Generation complete")
                    break
            except:
                pass
            await asyncio.sleep(1)
        
        await asyncio.sleep(3)
        
        # Extract text from response element
        if response_elem:
            text = await response_elem.inner_text()
            if text and len(text) > 50:
                return clean_response_text(text)
        
        # Fallback: get last response
        response_elements = await page.query_selector_all("[data-message-author-role='model']")
        if response_elements:
            last_response = response_elements[-1]
            text = await last_response.inner_text()
            if text and len(text) > 50:
                return clean_response_text(text)
        
        # Last resort: extract from page
        page_text = await page.evaluate("""
            () => {
                const bodyText = document.body.innerText;
                const titlesIndex = bodyText.indexOf('TITLES:');
                if (titlesIndex !== -1) {
                    return bodyText.substring(titlesIndex);
                }
                return bodyText;
            }
        """)
        
        if page_text and ('TITLES:' in page_text or 'Title 1:' in page_text):
            return clean_response_text(page_text)
        
        return ""
        
    except Exception as e:
        print(f"❌ Error extracting response: {e}")
        return ""


def clean_response_text(text: str) -> str:
    """Clean up extracted response"""
    text = text.strip()
    
    # Remove common UI elements
    cleanup_phrases = [
        "Gemini can make mistakes",
        "double-check",
        "Show drafts",
        "Copy code",
        "Use code with caution",
        "You stopped this response"
    ]
    
    for phrase in cleanup_phrases:
        text = text.replace(phrase, "")
    
    # Clean up whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    
    # Extract from TITLES: onwards
    if 'TITLES:' in text:
        titles_idx = text.find('TITLES:')
        text = text[titles_idx:]
    
    return text.strip()


def parse_gemini_response(response_text: str, title_count: int, desc_count: int, bullet_count: int) -> tuple:
    """Parse structured response from Gemini"""
    
    titles = []
    descriptions = []
    bullets = []
    
    try:
        print("🔍 Parsing response...")
        
        # Find section boundaries
        response_upper = response_text.upper()
        titles_start = response_upper.find("TITLES:")
        desc_start = response_upper.find("DESCRIPTIONS:")
        bullets_start = response_upper.find("BULLETS:")
        
        if titles_start == -1:
            print("⚠️  'TITLES:' section not found")
            return titles, descriptions, bullets
        
        # Extract sections
        if desc_start != -1:
            titles_section = response_text[titles_start + 7:desc_start]
        else:
            titles_section = response_text[titles_start + 7:]
        
        if desc_start != -1 and bullets_start != -1:
            desc_section = response_text[desc_start + 13:bullets_start]
        elif desc_start != -1:
            desc_section = response_text[desc_start + 13:]
        else:
            desc_section = ""
        
        if bullets_start != -1:
            bullets_section = response_text[bullets_start + 8:]
        else:
            bullets_section = ""
        
        # Parse TITLES
        for i in range(1, title_count + 1):
            pattern = rf'Title\s*{i}\s*:\s*(.+?)(?=Title\s*{i+1}\s*:|DESCRIPTIONS:|$)'
            match = re.search(pattern, titles_section, re.IGNORECASE | re.DOTALL)
            if match:
                content = ' '.join(match.group(1).strip().split())
                if len(content) > 10:
                    titles.append(content)
                    print(f"   ✓ Title {i}: {content[:60]}...")
        
        # Parse DESCRIPTIONS
        for i in range(1, desc_count + 1):
            pattern = rf'Description\s*{i}\s*:\s*(.+?)(?=Description\s*{i+1}\s*:|BULLETS:|$)'
            match = re.search(pattern, desc_section, re.IGNORECASE | re.DOTALL)
            if match:
                content = ' '.join(match.group(1).strip().split())
                if len(content) > 20:
                    descriptions.append(content)
                    print(f"   ✓ Description {i}: {content[:60]}...")
        
        # Parse BULLETS
        for i in range(1, bullet_count + 1):
            pattern = rf'Bullet\s*{i}\s*:\s*(.+?)(?=Bullet\s*{i+1}\s*:|$)'
            match = re.search(pattern, bullets_section, re.IGNORECASE | re.DOTALL)
            if match:
                content = ' '.join(match.group(1).strip().split())
                if len(content) > 10:
                    bullets.append(content)
                    print(f"   ✓ Bullet {i}: {content[:60]}...")
        
        return titles, descriptions, bullets
        
    except Exception as e:
        print(f"⚠️  Parsing error: {e}")
        return titles, descriptions, bullets


if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*70)
    print("    🎯 AI Content Generator - Text Only")
    print("="*70)
    print(f"\n🌐 Dashboard: http://localhost:8000/")
    print("\n✨ Features:")
    print("   • Define custom prompts for each content type")
    print("   • Provide reference/listing data")
    print("   • Control quantity and character length")
    print("   • Select and export generated content")
    print("   • No image processing - pure text generation")
    print("\n💾 Session: chrome_profile/ | Output: output/")
    print("="*70 + "\n")
    uvicorn.run("server:app", host="0.0.0.0", port=8002)