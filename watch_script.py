from tgtg import TgtgClient
from json import load, dump
from argparse import ArgumentParser
from shutil import copy
from telebotapi import TelegramBot, Chat, Message
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
tgtg_in_stock = []


def dump_to_config():
    global config
    global args

    dump(config, open(args.configs, "w+"), indent=4)


def dump_stock():
    global tgtg_in_stock
    global args

    dump(tgtg_in_stock, open(args.stock, "w+"), indent=4)


def main():
    global args
    global config
    global tgtg_in_stock

    def exit_no_config():
        logging.error("missing configs, cannot proceed.")
        return 2

    if args.configs is None:
        if os.path.exists("config.json"):
            config = load(open("config.json"))
            args.configs = "config.json"
        else:
            if os.path.exists("config.example.json"):
                logging.warning("no config found")
                if input("Make a copy of example? (y/N) ") in "yY":
                    copy("config.example.json", "config.json")
                    logging.warning("please compile the newly copied config.json, then rerun the program")
                    exit()
                else:
                    return exit_no_config()
            else:
                return exit_no_config()
    else:
        if os.path.exists(args.configs):
            config = load(open(args.configs))
        else:
            logging.error("cannot read %s: no such file or directory", args.configs)
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
        print(tgtg_creds)
        config['tgtg'] = tgtg_creds
        dump_to_config()
        tgtg_client = TgtgClient(access_token=config['tgtg']['access_token'],
                                 refresh_token=config['tgtg']['refresh_token'], user_id=config['tgtg']['user_id'],
                                 cookie=config['tgtg']['cookie'])
    except Exception as e:
        logging.error("Unexpected error")
        raise e

    try:
        bot_token = config['telegram']["bot_token"]
        if bot_token == "BOTTOKEN":
            raise KeyError
    except KeyError:
        logging.error(f"Failed to obtain Telegram bot token.\n Put it into config.json.")
        return 1

    try:
        t = TelegramBot(bot_token, safe_mode=True)
        t.bootstrap()
    except Exception as e:
        logging.error("error while bootstrapping the telegram bot:")
        raise e

    try:
        admin_chat_id = str(config['telegram']["admin_chat_id"])
        if admin_chat_id == "0":
            # Get chat ID
            pin = ''.join(random.choices(string.digits, k=6))
            print("Please type \"" + pin + "\" to the bot by the admin chat.")
            while admin_chat_id == "0":
                for u in t.get_updates():
                    if u.type == "text" and u.content.text == pin:
                        bot_chat_id = str(u.content.chat.id)
                        print("Your chat id:" + bot_chat_id)
                        config['telegram']['admin_chat_id'] = int(bot_chat_id)
                        dump_to_config()
        admin = Chat.by_id(admin_chat_id)

        bot_chat_id = str(config['telegram']["bot_chat_id"])
        if bot_chat_id == "0":
            # Get chat ID
            pin = ''.join(random.choices(string.digits, k=6))
            print("Please type \"" + pin + "\" to the bot by the target chat.")
            while bot_chat_id == "0":
                for u in t.get_updates():
                    if u.type == "text" and u.content.text == pin:
                        bot_chat_id = str(u.content.chat.id)
                        print("Your chat id:" + bot_chat_id)
                        config['telegram']['bot_chat_id'] = int(bot_chat_id)
                        dump_to_config()
        target = Chat.by_id(bot_chat_id)
    except KeyError:
        logging.error(f"Failed to obtain Telegram chat ID.")
        return 1
    except Exception as e:
        raise e

    # Init the favourites in stock list as a global variable
    tgtg_in_stock = list()
    if args.stock is None:
        args.stock = "tgtg_in_stock.json"

    if os.path.exists(args.stock):
        tgtg_in_stock = load(open(args.stock))
    else:
        logging.warning("%s will be created since it doesn't exists", args.stock)

    #
    # else:
    #     if os.path.exists("tgtg_in_stock.json"):
    #         args.stock = "tgtg_in_stock.json"
    #         try:
    #             tgtg_in_stock = json.load(open("tgtg_in_stock.json"))
    #         except Exception as e:
    #             logging.error("cannot load from %s:", args.stock)
    #             raise e

    def telegram_bot_sendtext(bot_message, only_to_admin=False):
        """
        Helper function: Send a message with the specified telegram bot.
        It can be specified if both users or only the admin receives the message
        Follow this article to figure out a specific chat_id: https://medium.com/@ManHay_Hong/how-to-create-a-telegram-bot-and-send-messages-with-python-4cf314d9fa3e
        """
        return t.sendMessage(target, bot_message, parse_mode="Markdown")

    def telegram_bot_sendimage(image_url, image_caption=None, only_admins=False):
        """
        For sending an image in Telegram, that can also be accompanied by an image caption
        """
        # Prepare the url for an telegram API call to send a photo
        return t.sendPhoto(target, image_url, image_caption)

    def telegram_bot_delete_message(message_id):
        """
        For deleting a Telegram message
        """
        t.deleteMessage(Message.by_id(message_id))

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
                localPickupStart = datetime.datetime.strptime(store['pickup_interval']['start'],
                                                              '%Y-%m-%dT%H:%M:%S%z').replace(
                    tzinfo=datetime.timezone.utc).astimezone(tz=None)
                localPickupEnd = datetime.datetime.strptime(store['pickup_interval']['end'],
                                                            '%Y-%m-%dT%H:%M:%S%z').replace(
                    tzinfo=datetime.timezone.utc).astimezone(tz=None)
                current_item['pickup_start'] = maya.parse(
                    localPickupStart).slang_date().capitalize() + " " + localPickupStart.strftime('%H:%M')
                current_item['pickup_end'] = maya.parse(
                    localPickupEnd).slang_date().capitalize() + " " + localPickupEnd.strftime('%H:%M')
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

        parsed_api = parse_tgtg_api(api_response)

        added, modified, deleted = 0, 0, 0

        def format_store(it):
            return f"[{it['store_name']}](https://share.toogoodtogo.com/item/{it['id']})"

        def prepare_text(it):
            message = f"🍽 There are {new_stock} new goodie bags at {format_store(it)}\n" \
                      f"_{it['description']}_\n" \
                      f"💰 *{it['price_including_taxes']}*/{it['value_including_taxes']}\n"
            if 'rating' in it:
                message += f"⭐️ {it['rating']}/5\n"
            if 'pickup_start' and 'pickup_end' in it:
                message += f"⏰ {it['pickup_start']} - {it['pickup_end']}\n"
            message += "ℹ️ toogoodtogo.com"
            return message

        # Go through all favourite items and compare the stock
        for item in parsed_api:
            try:
                old_stock = [stock['items_available'] for stock in tgtg_in_stock if stock['id'] == item['id']][0]
            except IndexError:
                old_stock = None
            try:
                item['msg_id'] = [stock['msg_id'] for stock in tgtg_in_stock if stock['id'] == item['id']][0]
                original_message = Message.by_id(item["msg_id"], target.id)
            except:
                original_message = None

            new_stock = item['items_available']

            # Check, if the stock has changed. Send a message if so.
            if new_stock != old_stock:
                # Check if the stock was replenished, send an encouraging image message
                if old_stock is None or original_message is None:
                    added += 1
                    text = prepare_text(item)
                    tg = t.sendPhoto(target, item['category_picture'], text)
                    item['msg_id'] = tg.id
                else:
                    text = prepare_text(item)
                    # try:
                    t.editMessageCaption(original_message, text)
                    # except TypeError as e:
                    #     if "description" in e and

                    upd_text = None
                    if new_stock == 0:
                        upd_text = f"Oh no! {format_store(item)} has sold out its bags😢"
                    elif new_stock > old_stock:
                        upd_text = f"New bags at {format_store(item)}!"
                    elif old_stock > new_stock > 2:
                        upd_text = f"Quick! Bags at {format_store(item)} are running short!"

                    if upd_text is not None:
                        t.sendMessage(
                            target,
                            upd_text,
                            reply_to_message=original_message,
                            a={"disable_web_page_preview": True}
                        )

        # Reset the global information with the newest fetch
        tgtg_in_stock = parsed_api
        dump_stock()

        # Print out some maintenance info in the terminal
        print(f"TGTG: API run at {time.ctime(time.time())} successful.")

        if added + modified + deleted > 0:
            t.sendMessage(admin, f"Updates sent to target: {added} added, {modified} modified, {deleted} deleted")
        # for item in parsed_api:
        #     print(f"{item['store_name']}({item['id']}): {item['items_available']}")

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
            print(traceback.format_exc())
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

    args = argp.parse_args()

    exit(main())
