![OmegaClaw banner](/docs/assets/banner.png)

# Meet Oma

Oma is the first Telegram agent built on the OmegaClaw framework. Interacting
with Oma is the fastest way to experience what we’re building with OmegaClaw.

<p align="center">
  <a href="https://t.me/ASI_Alliance">
    <img src="/docs/assets/tg-button.png" width="25%" alt="Chat with Oma">
  </a>
</p>

---

## Overview

OmegaClaw is a neural-symbolic agent framework built on the Hyperon AGI stack.
It unifies large language models with a formal symbolic layer to create a
stateful cognitive architecture capable of auditable inference, autonomous
self-improvement, and long-term persistence.

Unlike reactive, session-based agents, OmegaClaw operates in a continuous
execution loop, managing its own goals and providing auditable proof trails for
its reasoning.

The primary design criteria for OmegaClaw were simplicity, ease of extension,
and transparent implementation. The MeTTa core in [`src/`](/src) is about 400
significant lines; the Python modules next to it are thin bridges to the LLM
providers, the communication channels and the embedding store.

---

## Installation

Prerequisites: Git, Python 3.10 or later including dev headers, Pip and [venv](https://docs.python.org/3/library/venv.html) library, C compiler (for building [janus-swi](https://pypi.org/project/janus-swi/) library)

Under Ubuntu one can use the following command to install prerequisites:
```
sudo apt-get install git python3 python3-dev python3-pip python3-venv build-essential
```

Get [SWI-Prolog 10.0.2 or later](https://www.swi-prolog.org/).

Install OmegaClaw:
```
git clone https://github.com/trueagi-io/PeTTa
cd PeTTa
mkdir -p repos
git clone https://github.com/asi-alliance/OmegaClaw-Core.git repos/OmegaClaw-Core
git clone https://github.com/patham9/petta_lib_chromadb.git repos/petta_lib_chromadb
cp repos/OmegaClaw-Core/run.metta ./
```

Setup Python virtual environment (or use your own):
```
python3 -m venv ./.venv
source ./.venv/bin/activate
```

Install Python dependencies:
```
python3 -m pip install -r ./repos/OmegaClaw-Core/requirements.txt
```

On a CPU-only machine, or if you do not want to compute embeddings on GPU, install
the CPU build of `torch` in the same step so that the pinned version from
`requirements.txt` is not replaced by the CUDA wheel from PyPI:
```
python3 -m pip install \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple/ \
    torch==2.12.1 \
  && python3 -m pip install -r ./repos/OmegaClaw-Core/requirements.txt
```
---

## Run OmegaClaw in Docker

Ensure that you have [Docker installed](https://docs.docker.com/engine/install/)

Run OmegaClaw using the next command:
```
curl -fsSL https://raw.githubusercontent.com/asi-alliance/OmegaClaw-Core/refs/heads/main/scripts/omegaclaw | bash -s -- singularitynet/omegaclaw:latest
```

To run a specific version of OmegaClaw set version in `TAG` environment variable and run the following command:
```
export TAG=v0.1.18; curl -fsSL  https://github.com/asi-alliance/OmegaClaw-Core/raw/refs/tags/$TAG/scripts/omegaclaw | bash -s -- singularitynet/omegaclaw:$TAG
```

To stop the OmegaClaw Docker container:
```
docker stop omegaclaw
```

To restart the OmegaClaw Docker container:
```
docker start omegaclaw
```

To reset OmegaClaw's memory, use the `clean` subcommand. It removes the container
first, because the `omegaclaw-memory` volume cannot be deleted while a container
still references it:
```
./scripts/omegaclaw clean
```

The script accepts three subcommands — `start`, `stop` and `clean` — and the
following options for `start`:

| Option | Meaning |
|---|---|
| `-t <channel>` | Communication channel: `irc`, `telegram`, `slack`, `websocket`, `test`. |
| `-p <provider>` | LLM provider, see the [table below](#usage). Defaults to `ASICloud`. |
| `-d <image>` | Docker image. Defaults to `singularitynet/omegaclaw:latest`. |
| `-s <secret>` | Channel authentication secret. Defaults to `0000`. |
| `-g <url>` | OpenClaw execution agent URL; also enables the OpenClaw plugin. |

`start` removes any existing container named `omegaclaw` before creating a new
one, and always mounts the `omegaclaw-memory` volume. Neither the container name
nor the volume name is configurable.

To build the image from a source checkout instead of pulling it:
```
docker build -t omegaclaw:local .
```

---

## Usage

Before running the system you need to choose your LLM API provider and export the API key as the environment variable.
| Provider | Env var name | Notes |
|---|---|---|
| `Anthropic` (default) | `ANTHROPIC_API_KEY` | Claude models via the Anthropic API. |
| `OpenAI` | `OPENAI_API_KEY` | GPT models. Also reused by the OpenAI embedding provider below. |
| `ASICloud` | `ASI_API_KEY` |  MiniMax models via ASI Alliance inference endpoint (`inference.asicloud.cudos.org`). |
| `ASIOne` | `ASIONE_API_KEY` |  ASI1 Ultra model via ASI:One inference endpoint (`https://api.asi1.ai/v1`). |
| `OpenAIAPI` | `OPENAIAPI_API_KEY` |  Use OpenAI API with any endpoint and model. API endpoint and model are set via `openaiapi_url` and `model` command line parameters. |
| `OpenRouter` | `OPENROUTER_API_KEY` |  GLM model via OpenRouter inference endpoint. |
| `Test` | none | Mock provider used by the automated tests. Requires `TEST_SERVER_IP` pointing at the test controller on the host; it is not registered without it. |

`Anthropic` is the default in [`config/config.yaml`](/config/config.yaml). The
`scripts/omegaclaw` wrapper overrides it with `ASICloud` unless `-p` is given.
Each provider reads its model from its own `*_model` key, and the generic `model`
key overrides all of them.

Run the system via the following command which ensures the system is started from the root folder of PeTTa:
```
OMEGACLAW_AUTH_SECRET=<channel-secret> sh run.sh run.metta IRC_channel="<irc-channel>"
```
After start go to https://webchat.quakenet.org/ to communicate with the agent. Join `<irc-channel>` and after agent is joined send `auth <channel-secret>` message to authenticate yourself as an agent owner. Please replace `<irc-channel>` and `<channel-secret>` by your own values.

### Import Knowledge

If you are running OmegaClaw without Docker and would like to load it with preset knowledge, follow these steps:

1. Set EMBEDDING_PROVIDER in your environment. It can be set to either OpenAI or Local. OpenAI embeddings also require OPENAI_API_KEY to be set in your environment.

2. Run the script from the root folder of PeTTa:
```
  sh ./repos/OmegaClaw-Core/scripts/import_knowledge.sh
```
   The script writes to `CHROMA_DB_PATH`, which defaults to `/PeTTa/chroma_db`.
   Set it explicitly if your checkout lives elsewhere.

After the script finishes, your OmegaClaw bot will have the preset knowledge stored in its long-term memory (LTM).

If you want to skip preloading the knowledge then run `export IMPORT_KB_ON_START=0`

## Configuration Options

These are the following sources of the configuration parameters for the
OmegaClaw agent:
- command line parameters
- environment variables
- configuration file

OmegaClaw looks for parameters in each of the locations. Command line
parameters override environment variables which in turn override configuration
file values. Environment variables should be named `OMEGACLAW_<parameter>` in
order to separate them from other variables. For example to override the
default LLM model one can set an `OMEGACLAW_model` environment variable. The full
list of parameters with descriptions and default values can be found in
[default configuration file](/config/config.yaml).

Two properties of the lookup are worth knowing:

- **Inside the Docker image the environment variable level has no effect.**
  `entrypoint.sh` restarts the agent through `env -i` with a fixed allowlist, and
  `OMEGACLAW_DIR` is the only `OMEGACLAW_`-prefixed name on it. In a container,
  override parameters with command line arguments or with a mounted
  configuration file.
- **If the same key appears twice on the command line, the last occurrence wins.**
  This is how an argument added after the ones supplied by `entrypoint.sh` takes
  effect.

The first value resolved for a key is cached for the lifetime of the process,
including the case where the value came from the built-in default.

The configuration file location can be specified manually using `config` option:
```sh
sh run.sh run.metta config=<config.yaml path>
```

The LLM API keys (see [table above](#usage)) and communication channel tokens
from the table below are passed via environment variables (without `OMEGACLAW_`
prefix) to prevent agent accessing them.

| Environment variable | Meaning |
|---|---|
| `TG_BOT_TOKEN` | Telegram bot token. |
| `MM_BOT_TOKEN` | Mattermost bot token. |
| `SL_BOT_TOKEN` | Slack bot token (`xoxb-...`). |

### How secrets are kept away from the agent

In the Docker image the separation is enforced, not merely conventional:

1. `entrypoint.sh` starts an nginx instance that holds the keys and tokens. The
   proxy configuration is generated from
   [`proxy/nginx.conf.template`](/proxy/nginx.conf.template) by `envsubst`, which
   substitutes the secrets into a file readable only by the proxy user.
2. The agent is then started through `env -i` with a small allowlist, so its own
   process environment contains no keys or tokens at all. This can be confirmed
   from the host with `/proc/<pid>/environ` of the `swipl` process — the file is
   not readable from inside the container, not even as root.
3. The agent reaches the provider APIs through `GATEWAY_URL`, which
   `entrypoint.sh` passes as a command line argument (an environment variable
   would not survive `env -i`). The proxy attaches the credentials on the way
   out.

As a consequence, a Docker-based deployment always routes provider and channel
traffic through the local proxy. The one component that talks to the network
directly is the DuckDuckGo web search in `src/websearch.py`, which needs no
credentials.

---

## Tests

The test suites and the commands that run them are defined in
[`.github/workflows/autotests.yml`](/.github/workflows/autotests.yml). There are
four entry points:

```
./tests/pytest.sh                                 # unit tests, from the repository root
cd Autotests && pytest -s -v @run_mandatory       # blocking suite
cd Autotests && pytest -s -v @run_optional        # non-blocking suite
docker exec -e PETTA_PATH=/PeTTa omegaclaw \
    /PeTTa/repos/OmegaClaw-Core/tests/mettatest.sh
```

The `Autotests` suites drive a running container, so start one first. CI uses a
single container created with `-p Test -t test -g <openclaw-url>` and installs
`pytest` as the only additional dependency. Two details are easy to miss:

- `@run_mandatory` and `@run_optional` are plain lists of test files. A file
  added under `Autotests/` but not listed in one of them is never collected.
- Without `-g`, the OpenClaw delegation tests skip themselves and the suite still
  reports success, so the run covers less than it appears to.

`mettatest.sh` requires `PETTA_PATH` and an absolute path, because the working
directory inside the container is `/PeTTa` rather than the repository root.

---

## Documentation

Full documentation lives in [`docs/`](./docs/README.md): introduction,
tutorials, and API reference as a flat set of markdown files.

---

### Disclaimer

<sub>OmegaClaw is experimental, open-source software developed by SingularityNET Foundation, a Swiss foundation, and distributed and promoted by Superintelligence Alliance Ltd., a Singapore company (collectively, the "Parties"), and is provided "AS IS" and "AS AVAILABLE," without warranty of any kind, express or implied, including but not limited to the implied warranties of merchantability, fitness for a particular purpose, and non-infringement. OmegaClaw is an autonomous AI agent that is designed to independently set goals, make decisions, and take actions (including actions that the user did not specifically request or anticipate) and whose behavior is influenced by large language models provided by third parties, the outputs of which are inherently non-deterministic. Depending on its configuration and the permissions granted to it, OmegaClaw may execute operating-system shell commands, read, write, modify, or delete files, access network resources, send and receive messages through connected communication channels, and modify its own skills, memory, and operational logic at runtime. OmegaClaw may also be susceptible to prompt injection and other adversarial manipulation techniques whereby malicious content embedded in data sources consumed by the agent could influence its behavior in unintended ways. OmegaClaw supports third-party skills and extensions that have not necessarily been reviewed, audited, or endorsed by either of the Parties and that may introduce security vulnerabilities, cause data loss, or result in unintended behavior including data exfiltration. OmegaClaw relies on third-party services, including large language model providers, whose availability, accuracy, cost, and conduct are outside the control of the Parties and whose use is subject to their respective terms, conditions, and privacy policies. The user is solely responsible for configuring appropriate access controls, sandboxing, and permission boundaries, for monitoring, supervising, and constraining OmegaClaw's actions, for ensuring that no sensitive personal data is exposed to the agent without adequate safeguards, and for all actions taken by OmegaClaw on the user's systems or on the user's behalf, including communications sent and files modified. The user is strongly advised to run OmegaClaw in an isolated environment with the minimum permissions necessary for the intended use case. To the maximum extent permitted by applicable law, in no event shall the Parties, their respective board members, directors, contributors, employees, or affiliates be liable for any direct, indirect, incidental, special, consequential, or exemplary damages (including but not limited to damages for loss of data, loss of profits, business interruption, unauthorized transactions, reputational harm, or any damages arising from the autonomous actions taken by OmegaClaw) however caused and on any theory of liability, whether in contract, strict liability, or tort (including negligence or otherwise), even if advised of the possibility of such damages. By downloading, installing, running, or otherwise using OmegaClaw, the user acknowledges that they have read, understood, and agreed to this disclaimer in its entirety. This disclaimer supplements but does not replace the terms of the MIT License under which OmegaClaw is released.</sub>
