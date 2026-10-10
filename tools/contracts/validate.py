"""Walidacja artefaktów E0 bez sieci i bez uruchamiania aplikacji."""
import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate as validate_openapi
from referencing import Registry, Resource

from catalog_checks import check_catalog
from domain_checks import check_domain
from markdown_checks import check_local_links
from nutrition_checks import verify_vectors
from source_checks import verify_source
from sync_checks import check_sync, check_scenario

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / 'contracts'
DIALECT = 'https://json-schema.org/draft/2020-12/schema'
FORMATS = FormatChecker()


@FORMATS.checks('iana-time-zone')
def valid_zone(value):
    if not isinstance(value, str):
        return True
    try:
        ZoneInfo(value)
        return True
    except (ValueError, ZoneInfoNotFoundError):
        return False


def read(path):
    def unique_keys(pairs):
        data = {}
        for key, value in pairs:
            assert key not in data, f'Duplicate JSON key: {path}: {key}'
            data[key] = value
        return data
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_keys)


def target(ref, base):
    path, _, fragment = ref.partition('#')
    assert not urlsplit(path).scheme, f'Non-local $ref: {ref}'
    filename = (base.parent / unquote(path)).resolve() if path else base
    assert filename.is_relative_to(CONTRACTS), f'Ref outside contracts: {ref}'
    data = yaml.safe_load(filename.read_text(encoding='utf-8')) if filename.suffix == '.yaml' else read(filename)
    for part in fragment.split('/')[1:]:
        data = data[part.replace('~1', '/').replace('~0', '~')]
    return filename, fragment, data


def walk_refs(value, base):
    if isinstance(value, dict):
        if '$ref' in value:
            target(value['$ref'], base)
        for nested in value.values():
            walk_refs(nested, base)
    elif isinstance(value, list):
        for nested in value:
            walk_refs(nested, base)


def expanded(value, base, stack=()):
    if isinstance(value, dict):
        if '$ref' in value:
            filename, fragment, data = target(value['$ref'], base)
            identity = (filename, fragment)
            assert identity not in stack, f'Unexpected recursive schema: {identity}'
            return {**expanded(data, filename, (*stack, identity)),
                    **{key: expanded(item, base, stack) for key, item in value.items() if key != '$ref'}}
        return {key: expanded(item, base, stack) for key, item in value.items()}
    if isinstance(value, list):
        return [expanded(item, base, stack) for item in value]
    return value


def nested_errors(errors):
    for error in errors:
        yield error
        yield from nested_errors(error.context)


def main():
    schemas = sorted((CONTRACTS / 'schemas').glob('*.json'))
    registry = Registry()
    for path in schemas:
        data = read(path)
        assert data['$schema'] == DIALECT, path
        Draft202012Validator.check_schema(data)
        walk_refs(data, path)
        registry = registry.with_resource(path.as_uri(), Resource.from_contents(data))

    def validate(value, schema_ref, base):
        path, fragment, _ = target(schema_ref, base)
        validator = Draft202012Validator({'$ref': path.as_uri() + '#' + fragment}, registry=registry, format_checker=FORMATS)
        return list(validator.iter_errors(value))

    def semantics(value, schema_ref):
        definition = schema_ref.rsplit('/', 1)[-1]
        if 'catalog.schema.json' in schema_ref:
            return check_catalog(value, definition)
        if 'sync.schema.json' in schema_ref:
            return check_scenario(value) if definition == 'Scenario' else check_sync(value, definition)
        return check_domain(value, definition)

    api_path = CONTRACTS / 'openapi/design-v1.yaml'
    api = yaml.safe_load(api_path.read_text(encoding='utf-8'))
    assert api['openapi'] == '3.1.1' and api['jsonSchemaDialect'] == DIALECT
    assert api['info']['x-status'] == 'design draft'
    walk_refs(api, api_path)
    validate_openapi(expanded(api, api_path))
    ids = []
    api_example_count = 0
    for route, methods in api['paths'].items():
        for method, op in methods.items():
            if method not in {'get', 'post', 'put', 'delete', 'patch'}:
                continue
            ids.append(op['operationId'])
            assert op.get('description') and op['responses'] and 'security' in op, route
            assert '200' in op['responses'], route
            for parameter in op.get('parameters', []):
                assert 'example' in parameter, f'Missing parameter example: {route}'
                parameter_schema = expanded(parameter['schema'], api_path)
                assert Draft202012Validator(parameter_schema, format_checker=FORMATS).is_valid(parameter['example']), parameter
            for container in [op.get('requestBody', {}), *op['responses'].values()]:
                for mime, body in container.get('content', {}).items():
                    if mime != 'application/json':
                        continue
                    assert body.get('examples'), f'Missing HTTP example: {route}'
                    for example in body['examples'].values():
                        filename = (api_path.parent / example['externalValue']).resolve()
                        assert filename.is_relative_to(CONTRACTS / 'examples')
                        value = read(filename)
                        problems = validate(value, body['schema']['$ref'], api_path)
                        assert not problems, f'OpenAPI example {filename}: {problems[0] if problems else ""}'
                        api_example_count += 1
    assert len(ids) == len(set(ids)), 'Duplicate operationId'
    assert '/me' not in api['paths'] or 'patch' not in api['paths']['/me']
    assert 'post' not in api['paths'].get('/me/goals', {})

    index_path = CONTRACTS / 'examples/index.json'
    index = read(index_path)
    assert not validate(index, '../schemas/fixtures.schema.json#/$defs/Index', index_path), 'Invalid fixture registry'
    seen, example_ids = set(), set()
    valid_count = invalid_count = scenario_count = 0
    for entry in index['examples']:
        assert entry['id'] not in example_ids and entry['purpose'] and entry['detection_layer']
        assert entry['server']['result'] == 'not_executed' and entry['server']['stage'] in {'E1','E2','E3','E4','E5'}
        example_ids.add(entry['id'])
        path = (index_path.parent / entry['path']).resolve()
        assert path.is_relative_to(index_path.parent) and path not in seen, path
        seen.add(path)
        value = read(path)
        errors = validate(value, entry['schema'], index_path)
        expected = entry['local']
        codes = semantics(value, entry['schema']) if not errors else []
        if expected['result'] == 'valid':
            assert not errors and not codes, f'{entry["id"]}: {errors[0] if errors else codes}'
            valid_count += 1
        else:
            assert expected['result'] == 'invalid', entry
            if expected['layer'] == 'schema':
                assert expected['reason'] in {e.validator for e in nested_errors(errors)}, f'{entry["id"]}: wrong schema rejection {errors}'
            else:
                assert not errors and expected['reason'] in codes, f'{entry["id"]}: wrong semantic rejection {errors or codes}'
            invalid_count += 1
        if '/Scenario' in entry['schema']:
            scenario_count += 1
            for step in value['steps']:
                if step['kind'] != 'http':
                    continue
                method = 'post' if step['endpoint'] == 'push' else 'get'
                operation = api['paths']['/sync/' + step['endpoint']][method]
                response_schema = operation['responses'][str(step['expected_status'])]['content']['application/json']['schema']['$ref']
                assert not validate(step['response'], response_schema, api_path), f'Scenario diverges from OpenAPI: {entry["id"]}'
                if method == 'post':
                    request_schema = operation['requestBody']['content']['application/json']['schema']['$ref']
                    assert not validate(step['request'], request_schema, api_path), f'Scenario request diverges from OpenAPI: {entry["id"]}'
    files = {p.resolve() for folder in ['valid','invalid','scenarios'] for p in (index_path.parent / folder).glob('*.json')}
    assert files == seen, f'Orphan/missing examples: {files ^ seen}'
    source = index['source_material']
    assert source['status'] == 'unverified_source_not_contract'
    source_path = (ROOT / source['path']).resolve()
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source['sha256'], 'Source material changed'
    manifest = read(CONTRACTS / 'examples/valid/catalog-manifest.json')
    package_path = CONTRACTS / 'examples/valid/catalog-demo.json'
    compressed = (package_path.parent / manifest['path']).read_bytes()
    assert len(compressed) == manifest['compressed_bytes'] <= 10 * 1024 * 1024
    assert hashlib.sha256(compressed).hexdigest() == manifest['sha256']
    uncompressed = gzip.decompress(compressed)
    assert uncompressed == package_path.read_bytes()
    assert len(uncompressed) == manifest['uncompressed_bytes'] <= 50 * 1024 * 1024
    package = read(package_path)
    for key in ['package_id','release','schema_version','min_reader_version','published_at','counts','kind']:
        assert manifest[key] == package[key], f'Manifest mismatch: {key}'
    assert set(manifest['source_ids']) == {source['source_id'] for source in package['sources']}
    binary_files = {p.resolve() for p in (index_path.parent / 'valid').glob('*.gz')}
    assert binary_files == {(index_path.parent / b['path']).resolve() for b in index['binary_fixtures']}
    normalization_count = verify_source(source_path, package)
    vectors_path = CONTRACTS / 'test-vectors/nutrition-v1.json'
    assert not validate(read(vectors_path), '../schemas/fixtures.schema.json#/$defs/NutritionVectors', vectors_path), 'Invalid nutrition vector structure'
    vector_count, day_count = verify_vectors(vectors_path)
    local_links = 0
    docs = [ROOT/'README.md', ROOT/'WYMAGANIA_PROJEKTOWE.md', *sorted((ROOT/'docs').glob('*.md')), *sorted((ROOT/'docs/e0').glob('*.md')), CONTRACTS/'README.md']
    for path in docs:
        contents = path.read_text(encoding='utf-8')
        if path.parent == ROOT/'docs/e0' or path == CONTRACTS/'README.md':
            assert contents.splitlines()[0].endswith('- osoba 2'), path
        local_links += check_local_links(path)
    result = subprocess.run(['git','diff','--check'], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    print(f'PASS E0 | Python {sys.version.split()[0]} | schemas={len(schemas)} | endpoints={len(ids)} | HTTP examples={api_example_count}')
    print(f'PASS examples valid={valid_count} invalid={invalid_count} scenarios={scenario_count}; refs/formats/orphans/source/gzip/manifest')
    print(f'PASS Decimal vectors={vector_count}; day completeness={day_count}; source normalizations={normalization_count}; local links={local_links}; git diff --check')
    print('NOT EXECUTED: server transactions, PostgreSQL, Room, Kotlin, OIDC, deployment (E1-E5).')


if __name__ == '__main__':
    main()
