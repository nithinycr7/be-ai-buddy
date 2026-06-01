"""
Eval-only (NOT committed): regenerate the 'Internal Energy' engine world config
with the updated prompt (which now routes thermodynamics topics to world_type=gas
instead of the orbital 'scale' world). Saves to the engine_configs cache for the
grades the Explore tab requests.
"""
import asyncio

TOPIC_SLUG = "internal-energy"
TOPIC = "Internal Energy"
SUBJECT = "Science"
GRADES = [8, 9]


async def main():
    from app.services.engine_config_generator import generate_engine_config
    from app.services.engine_config_cache import save_config, CURRENT_PROMPT_VERSION

    print(f"prompt version: {CURRENT_PROMPT_VERSION}")
    config, gen_ms, model = await generate_engine_config(
        topic=TOPIC, subject=SUBJECT, grades=GRADES, board="CBSE",
    )
    wt = config.get("world_type")
    print(f"generated world_type = {wt}  (model={model}, {gen_ms}ms)")
    has_gas = "gasWorld" in config
    has_scale = "scaleWorld" in config
    print(f"gasWorld present: {has_gas} | scaleWorld present: {has_scale}")
    if has_gas:
        gw = config["gasWorld"]
        print(f"  count={gw.get('count')} | molecules={[m.get('name') for m in gw.get('molecules', [])]}")

    if wt != "gas":
        print("\n⚠️  LLM did NOT choose 'gas' — NOT saving. (Will hand-author instead.)")
        return

    for g in GRADES:
        await save_config(topic_slug=TOPIC_SLUG, grade=g, config=config,
                          generation_ms=gen_ms, gemini_model=model, force=True)
    print(f"\n✅ saved gas config for {TOPIC_SLUG} grades {GRADES}")


if __name__ == "__main__":
    asyncio.run(main())
