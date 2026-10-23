from backend.models.research import Profile


class Profiler:
    async def run(self, ctx, sample):
        async with ctx.step("profiler", "Profile the response structure") as progress:
            profile = Profile()
            record_sets = []

            def walk(value, path="", depth=0):
                profile.nesting_depth = max(profile.nesting_depth, depth)
                if depth > 30:
                    return
                if isinstance(value, list):
                    if value and all(isinstance(item, dict) for item in value):
                        profile.arrays_of_objects.append(path or "$")
                        record_sets.append((path or "$", value[:100]))
                    for item in value[:20]:
                        walk(item, path, depth + 1)
                elif isinstance(value, dict):
                    for key, item in list(value.items())[:100]:
                        walk(item, f"{path}.{key}".strip("."), depth + 1)

            walk(sample)
            profile.nested = profile.nesting_depth > 2
            if record_sets:
                profile.record_path, records = max(record_sets, key=lambda item: len(item[1]))
                for key in records[0]:
                    values = [row.get(key) for row in records]
                    if (
                        (key.lower() in {"id", "uuid", "code"} or key.lower().endswith("_id"))
                        and all(isinstance(v, (int, str)) for v in values)
                        and len(set(values)) == len(values)
                    ):
                        profile.primary_keys.append(key)
                    if any(token in key.lower() for token in ("date", "time")) and all(
                        isinstance(v, (str, int, float)) for v in values
                    ):
                        profile.date_fields.append(key)
            elif isinstance(sample, dict):
                profile.record_path = next(
                    (key for key, value in sample.items() if isinstance(value, list)), None
                )
            progress(
                f"Depth {profile.nesting_depth}; {len(profile.arrays_of_objects)} record arrays"
            )
            return profile
