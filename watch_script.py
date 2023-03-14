from tgtg import TgtgClient
from json import load, dump
from argparse import ArgumentParser
from shutil import copy
from telebotapi import TelegramBot, Chat, Message, exceptions
from copy import deepcopy
import schedule
import time
import os
import traceback
import maya
import datetime
import logging
import random
import string


config = {}
tgtg_in_stock = {}
logger = logging.getLogger("am_bot")


def dump_to_config():
    global config
    global args

    dump(config, open(args.configs, "w+"), indent=4)


def dump_stock():
    global tgtg_in_stock
    global args

    to_dump = deepcopy(tgtg_in_stock)
    dump(to_dump, open(args.stock, "w+"), indent=4)


def main():
    global args
    global config
    global tgtg_in_stock

    def exit_no_config():
        logger.error("missing configs, cannot proceed.")
        return 2

    if args.configs is None:
        if os.path.exists("config.json"):
            config = load(open("config.json"))
            args.configs = "config.json"
        else:
            if os.path.exists("config.example.json"):
                logger.warning("no config found")
                if input("Make a copy of example? (y/N) ") in "yY":
                    copy("config.example.json", "config.json")
                    logger.warning("please compile the newly copied config.json, then rerun the program")
                    exit()
                else:
                    return exit_no_config()
            else:
                return exit_no_config()
    else:
        if os.path.exists(args.configs):
            config = load(open(args.configs))
        else:
            logger.error("cannot read %s: no such file or directory", args.configs)
            return exit_no_config()

    def validate_config(c):
        if "tgtg" not in c or "telegram" not in c or "location" not in c:
            return

        for i in ("access_token", "refresh_token", "user_id", "cookie"):
            if i not in c["tgtg"]:
                return

        for i in ("long", "lat", "range"):
            if i not in c["location"]:
                return

        for i in ("bot_token", "bot_chat_id", "admin_chat_id"):
            if i not in c["location"]:
                return

    validate_config(config)

    try:
        # Create the tgtg client with my credentials
        tgtg_client = TgtgClient(access_token=config['tgtg']['access_token'],
                                 refresh_token=config['tgtg']['refresh_token'], user_id=config['tgtg']['user_id'],
                                 cookie=config["tgtg"]["cookie"])
    except KeyError:
        email = input("Type your TooGoodToGo email address: ")
        client = TgtgClient(email=email)
        tgtg_creds = client.get_credentials()
        logger.debug(tgtg_creds)
        config['tgtg'] = tgtg_creds
        dump_to_config()
        tgtg_client = TgtgClient(access_token=config['tgtg']['access_token'],
                                 refresh_token=config['tgtg']['refresh_token'], user_id=config['tgtg']['user_id'],
                                 cookie=config['tgtg']['cookie'])
    except Exception as e:
        logger.error("Unexpected error")
        raise e

    try:
        bot_token = config['telegram']["bot_token"]
        if bot_token == "BOTTOKEN":
            raise KeyError
    except KeyError:
        logger.error(f"Failed to obtain Telegram bot token.\n Put it into config.json.")
        return 1

    try:
        t = TelegramBot(bot_token, safe_mode=True)
        t.bootstrap()
    except Exception as e:
        logger.error("error while bootstrapping the telegram bot:")
        raise e

    try:
        admin_chat_id = str(config['telegram']["admin_chat_id"])
        if admin_chat_id == "0":
            # Get chat ID
            pin = ''.join(random.choices(string.digits, k=6))
            logger.info("Please type \"" + pin + "\" to the bot by the admin chat.")
            while admin_chat_id == "0":
                for u in t.get_updates():
                    if u.type == "text" and u.content.text == pin:
                        bot_chat_id = str(u.content.chat.id)
                        logger.debug("Your chat id:" + bot_chat_id)
                        config['telegram']['admin_chat_id'] = int(bot_chat_id)
                        dump_to_config()
        admin = Chat.by_id(admin_chat_id)

        bot_chat_id = str(config['telegram']["bot_chat_id"])
        if bot_chat_id == "0":
            # Get chat ID
            pin = ''.join(random.choices(string.digits, k=6))
            logger.info("Please type \"" + pin + "\" to the bot by the target chat.")
            while bot_chat_id == "0":
                for u in t.get_updates():
                    if u.type == "text" and u.content.text == pin:
                        bot_chat_id = str(u.content.chat.id)
                        logger.debug("Your chat id:" + bot_chat_id)
                        config['telegram']['bot_chat_id'] = int(bot_chat_id)
                        dump_to_config()
        target = Chat.by_id(bot_chat_id)
    except KeyError:
        logger.error(f"Failed to obtain Telegram chat ID.")
        return 1
    except Exception as e:
        raise e

    # Init the favourites in stock list as a global variable
    tgtg_in_stock = {}
    if args.stock is None:
        args.stock = "tgtg_in_stock.json"

    if os.path.exists(args.stock):
        tgtg_in_stock = load(open(args.stock))
    else:
        logger.warning("%s will be created since it doesn't exists", args.stock)

    def parse_tgtg_api(api_result):
        """
        For fideling out the few important information out of the api response
        """
        result = list()
        # Go through all stores, that are returned with the api
        for store in api_result:
            current_item = dict()
            current_item['id'] = store['item']['item_id']
            current_item['store_name'] = store['store']['store_name']
            current_item['items_available'] = store['items_available']
            if current_item['items_available'] == 0:
                result.append(current_item)
                continue
            current_item['description'] = store['item']['description']
            current_item['category_picture'] = store['item']['cover_picture']['current_url']
            current_item['price_including_taxes'] = str(store['item']['price_including_taxes']['minor_units'])[
                                                    :-(store['item']['price_including_taxes']['decimals'])] + "." + str(
                store['item']['price_including_taxes']['minor_units'])[-(
            store['item']['price_including_taxes']['decimals']):] + store['item']['price_including_taxes']['code']
            current_item['value_including_taxes'] = str(store['item']['value_including_taxes']['minor_units'])[
                                                    :-(store['item']['value_including_taxes']['decimals'])] + "." + str(
                store['item']['value_including_taxes']['minor_units'])[-(
            store['item']['value_including_taxes']['decimals']):] + store['item']['value_including_taxes']['code']
            try:
                local_pickup_start = datetime.datetime.strptime(store['pickup_interval']['start'],
                                                                '%Y-%m-%dT%H:%M:%S%z').replace(
                    tzinfo=datetime.timezone.utc).astimezone(tz=None)
                local_pickup_end = datetime.datetime.strptime(store['pickup_interval']['end'],
                                                              '%Y-%m-%dT%H:%M:%S%z').replace(
                    tzinfo=datetime.timezone.utc).astimezone(tz=None)
                current_item['pickup_start'] = maya.parse(
                    local_pickup_start).slang_date().capitalize() + " " + local_pickup_start.strftime('%H:%M')
                current_item['pickup_end'] = maya.parse(
                    local_pickup_end).slang_date().capitalize() + " " + local_pickup_end.strftime('%H:%M')
            except KeyError:
                current_item['pickup_start'] = None
                current_item['pickup_end'] = None
            try:
                current_item['rating'] = round(store['item']['average_overall_rating']['average_overall_rating'], 2)
            except KeyError:
                current_item['rating'] = None
            result.append(current_item)
        return result

    def toogoodtogo():
        """
        Retrieves the data from tgtg API and selects the message to send.
        """

        # Get the global variable of items in stock
        global tgtg_in_stock

        # Get all favorite items
        api_response = tgtg_client.get_items(
            favorites_only=False,
            latitude=config['location']['lat'],
            longitude=config['location']['long'],
            radius=config['location']['range'],
            page_size=300
        )

        parsed_api = {item["id"]: item for item in parse_tgtg_api(api_response)}

        added, modified, deleted = 0, 0, 0

        def format_store(it):
            return f"[{it['store_name']}](https://share.toogoodtogo.com/item/{it['id']})"

        def prepare_text(it):
            if "description" not in it:
                message = it["msg"]["body"]
            else:
                message = f"🍽 There are {{}} bags at {format_store(it)}\n" \
                          f"_{it['description']}_\n" \
                          f"💰 *{it['price_including_taxes']}*/{it['value_including_taxes']}\n"
                if 'rating' in it:
                    message += f"⭐️ {it['rating']}/5\n"
                if 'pickup_start' and 'pickup_end' in it:
                    message += f"⏰ {it['pickup_start']} - {it['pickup_end']}\n"
                message += "ℹ️ toogoodtogo.com"
                it["msg"]["body"] = message
            return message

        def quote(m, o_s, n_s, it):
            upd_text = None
            if n_s == 0:
                upd_text = f"Oh no! {format_store(item)} has sold out its bags 😢"
            elif n_s > o_s:
                upd_text = f"{format_store(item)} added {n_s - o_s} bags!"
            elif o_s > n_s <= 1:
                upd_text = f"Quick! Only one bag left at {format_store(item)}!"

            if upd_text is not None:
                if "update" in it["msg"] and it["msg"]["update"] is not None:
                    try:
                        t.deleteMessage(Message.by_id(it["msg"]["update"], target.id))
                    except exceptions.MessageNotFound:
                        pass
                it["msg"]["update"] = t.sendMessage(
                    target,
                    upd_text,
                    reply_to_message=m,
                    a={"disable_web_page_preview": True}
                ).id

        def new_message(it, n_s):
            txt = prepare_text(it).format(n_s)
            tg = t.sendPhoto(target, it["category_picture"], txt)
            it["msg"]["id"] = tg.id

        # Go through all favourite items and compare the stock
        for id_, item in parsed_api.items():
            try:
                old_stock = tgtg_in_stock[id_]["items_available"]
                item['msg'] = tgtg_in_stock[id_]["msg"]
                try:
                    om = Message.by_id(item["msg"]["id"], target.id)
                except KeyError:
                    om = None
            except KeyError:
                item["msg"] = {}
                old_stock = None
                om = None

            new_stock = item['items_available']

            # Check, if the stock has changed. Send a message if so.

            if new_stock != 0 and (old_stock is None or om is None):
                new_message(item, new_stock)
            elif old_stock is not None:
                if new_stock != old_stock:
                    text = prepare_text(item).format(new_stock)
                    try:
                        try:
                            t.editMessageCaption(om, text)
                        except exceptions.MessageNotModified:
                            pass
                        quote(om, old_stock, new_stock, item)
                    except exceptions.MessageNotFound:
                        if new_stock > 0:
                            new_message(item, new_stock)

        # Reset the global information with the newest fetch
        tgtg_in_stock = parsed_api
        dump_stock()

        # Print out some maintenance info in the terminal
        logger.info(f"TGTG: API run at {time.ctime(time.time())} successful.")

        if added + modified + deleted > 0:
            t.sendMessage(admin, f"Updates sent to target: {added} added, {modified} modified, {deleted} deleted")

    def still_alive():
        """
        This function gets called every 24 hours and sends a 'still alive' message to the admin.
        """
        message = f"Current time: {time.ctime(time.time())}. The bot is still running. "
        t.sendMessage(admin, message)

    def refresh():
        """
        Function that gets called via schedule every 1 minute.
        Retrieves the data from services APIs and selects the messages to send.
        """
        try:
            toogoodtogo()
        except:
            logger.error(traceback.format_exc())
            t.sendMessage(admin, "Error occured: \n```" + str(traceback.format_exc()) + "```")

    # Use schedule to set up a recurrent checking
    schedule.every(1).minutes.do(refresh)
    schedule.every(24).hours.do(still_alive)

    # Description of the service, that gets send once
    t.sendMessage(
        admin,
        "The bot script has started successfully. The bot checks every 1 minute, if there is something new at "
        "TooGoodToGo. Every 24 hours, the bots sends a \"still alive\" message.")
    refresh()
    try:
        while True:
            # run_pending
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        t.sendMessage(admin, f"Shutting down bot. Reason: admin interrupt")
    except:
        reason = f"exception: \n```{traceback.format_exc()}```"
        t.sendMessage(admin, f"Shutting down bot. Reason: {reason}")


if __name__ == "__main__":
    argp = ArgumentParser(prog="tgtg_bot")
    argp.add_argument("--configs", required=False, help="Specify different location for config files")
    argp.add_argument("--stock", required=False, help="Specify different location for tgtg stock file")
    argp.add_argument("--log", default=1, type=int, help="Specify verbosity")

    args = argp.parse_args()
    logger.setLevel(logging.DEBUG)
    logger.getEffectiveLevel()

    exit(main())
